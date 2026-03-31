"""
FHIR R4 → OneClick sync engine.

Maps FHIR resources to local SQLAlchemy models:
  Patient         → Patient
  Condition       → PatientProblem (ICD-10)
  MedicationRequest → PatientMedication
  Observation     → PatientVital / PatientLab
  Procedure       → CptCode (upsert reference data)
"""
import uuid
from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from app.models.patient import Patient, PatientProblem, PatientMedication, PatientVital, PatientLab
from app.models.codes import CptCode, Icd10Code
from app.integrations.fhir.client import FHIRClient

STATE_ABBR = {
    "Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA",
    "Colorado":"CO","Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA",
    "Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA","Kansas":"KS",
    "Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD","Massachusetts":"MA",
    "Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO","Montana":"MT",
    "Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ","New Mexico":"NM",
    "New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH","Oklahoma":"OK",
    "Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC",
    "South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT",
    "Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY",
    "District of Columbia":"DC",
}

def _normalize_state(val: Optional[str]) -> Optional[str]:
    if not val:
        return None
    if len(val) <= 2:
        return val.upper()
    return STATE_ABBR.get(val.strip(), val[:2].upper())

# LOINC codes → vital sign fields
VITAL_LOINC_MAP = {
    "8480-6":  "bp_systolic",
    "8462-4":  "bp_diastolic",
    "8867-4":  "heart_rate",
    "8310-5":  "temperature",
    "9279-1":  "respiratory_rate",
    "59408-5": "spo2",
    "29463-7": "weight_kg",
    "8302-2":  "height_cm",
    "39156-5": "bmi",
    "72514-3": "pain_score",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(val: Optional[str]) -> Optional[date]:
    if not val:
        return None
    try:
        return date.fromisoformat(val[:10])
    except (ValueError, TypeError):
        return None


def _parse_datetime(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _map_gender(fhir_gender: str) -> str:
    return {"male": "male", "female": "female", "other": "other", "unknown": "unknown"}.get(
        (fhir_gender or "").lower(), "unknown"
    )


def _ref_id(reference: str) -> Optional[str]:
    """Extract ID from FHIR reference like 'Patient/abc123'."""
    if reference and "/" in reference:
        return reference.split("/")[-1]
    return reference


def _coding_value(codeable: dict, system_keyword: str) -> Optional[str]:
    for c in codeable.get("coding", []):
        if system_keyword in c.get("system", ""):
            return c.get("code")
    return None


# ── Patient sync ──────────────────────────────────────────────────────────────

def sync_patients(client: FHIRClient, db: Session, org_id: uuid.UUID, limit: int = 100) -> dict:
    created, updated, skipped = 0, 0, 0
    count = 0

    for res in client.paginate("Patient"):
        if count >= limit:
            break
        count += 1

        fhir_id = res.get("id")
        if not fhir_id:
            skipped += 1
            continue

        # Name
        names = res.get("name", [])
        name = next((n for n in names if n.get("use") == "official"), names[0] if names else {})
        last_name = name.get("family") or "Unknown"
        given = name.get("given", [])
        first_name = given[0] if given else "Unknown"
        middle_name = given[1] if len(given) > 1 else None

        # DOB + gender
        dob = _parse_date(res.get("birthDate"))
        if not dob:
            skipped += 1
            continue
        gender = _map_gender(res.get("gender", "unknown"))

        # Contact
        telecom = res.get("telecom", [])
        phone = next((t["value"] for t in telecom if t.get("system") == "phone"), None)
        email = next((t["value"] for t in telecom if t.get("system") == "email"), None)

        # Address
        addrs = res.get("address", [])
        addr = next((a for a in addrs if a.get("use") == "home"), addrs[0] if addrs else {})
        lines = addr.get("line", [])

        mrn = f"FHIR-{fhir_id}"
        existing = db.query(Patient).filter(
            (Patient.fhir_patient_id == fhir_id) | (Patient.mrn == mrn)
        ).first()

        if existing:
            existing.first_name = first_name
            existing.last_name = last_name
            existing.middle_name = middle_name
            existing.date_of_birth = dob
            existing.gender = gender
            existing.phone = phone or existing.phone
            existing.email = email or existing.email
            existing.address_line1 = lines[0] if lines else existing.address_line1
            existing.city = addr.get("city") or existing.city
            existing.state = _normalize_state(addr.get("state")) or existing.state
            existing.zip = addr.get("postalCode") or existing.zip
            existing.fhir_patient_id = fhir_id
            updated += 1
        else:
            patient = Patient(
                organization_id=org_id,
                mrn=mrn,
                fhir_patient_id=fhir_id,
                first_name=first_name,
                last_name=last_name,
                middle_name=middle_name,
                date_of_birth=dob,
                gender=gender,
                phone=phone,
                email=email,
                address_line1=lines[0] if lines else None,
                city=addr.get("city"),
                state=_normalize_state(addr.get("state")),
                zip=addr.get("postalCode"),
            )
            db.add(patient)
            created += 1

    db.commit()
    return {"patients_created": created, "patients_updated": updated, "patients_skipped": skipped}


# ── Conditions / ICD-10 sync ──────────────────────────────────────────────────

def sync_conditions(client: FHIRClient, db: Session, fhir_patient_id: str,
                    patient_db_id: uuid.UUID) -> dict:
    created, updated = 0, 0

    for res in client.paginate("Condition", {"patient": fhir_patient_id}):
        fhir_cond_id = res.get("id")
        code_block = res.get("code", {})
        icd_code = _coding_value(code_block, "icd") or _coding_value(code_block, "ICD")
        name = code_block.get("text") or (
            res.get("code", {}).get("coding", [{}])[0].get("display")
        ) or "Unknown"

        clinical_status = (
            res.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", "active")
        )
        status = "resolved" if clinical_status in ("resolved", "inactive", "remission") else "active"
        onset = _parse_date(res.get("onsetDateTime") or res.get("onsetPeriod", {}).get("start"))

        existing = db.query(PatientProblem).filter_by(fhir_condition_id=fhir_cond_id).first()
        if existing:
            existing.icd10_code = icd_code or existing.icd10_code
            existing.problem_name = name
            existing.status = status
            updated += 1
        else:
            prob = PatientProblem(
                patient_id=patient_db_id,
                icd10_code=icd_code,
                problem_name=name,
                status=status,
                onset_date=onset,
                fhir_condition_id=fhir_cond_id,
            )
            db.add(prob)
            created += 1

            if icd_code:
                _ensure_icd10(db, icd_code, name)

    db.commit()
    return {"conditions_created": created, "conditions_updated": updated}


def _ensure_icd10(db: Session, code: str, description: str):
    if not db.query(Icd10Code).filter_by(code=code).first():
        db.add(Icd10Code(
            code=code,
            description=description[:500],
            short_description=description[:100],
            billable=True,
            is_active=True,
        ))


# ── Medications sync ──────────────────────────────────────────────────────────

def sync_medications(client: FHIRClient, db: Session, fhir_patient_id: str,
                     patient_db_id: uuid.UUID) -> dict:
    created, updated = 0, 0

    for res in client.paginate("MedicationRequest", {"patient": fhir_patient_id}):
        fhir_med_id = res.get("id")
        med_block = res.get("medicationCodeableConcept", {})
        name = med_block.get("text") or (
            med_block.get("coding", [{}])[0].get("display")
        ) or "Unknown"
        rxnorm = _coding_value(med_block, "rxnorm")

        dosage = res.get("dosageInstruction", [{}])[0]
        dose_text = dosage.get("text")
        route = (dosage.get("route", {}).get("coding", [{}])[0].get("display"))
        frequency = (dosage.get("timing", {}).get("code", {}).get("text")
                     or dosage.get("timing", {}).get("repeat", {}).get("periodUnit"))

        status = res.get("status", "active")
        is_active = status in ("active", "draft")

        existing = db.query(PatientMedication).filter_by(fhir_medication_id=fhir_med_id).first()
        if existing:
            existing.medication_name = name
            existing.is_active = is_active
            existing.rx_norm_code = rxnorm or existing.rx_norm_code
            updated += 1
        else:
            med = PatientMedication(
                patient_id=patient_db_id,
                medication_name=name,
                dose=dose_text,
                route=route,
                frequency=frequency,
                is_active=is_active,
                rx_norm_code=rxnorm,
                fhir_medication_id=fhir_med_id,
            )
            db.add(med)
            created += 1

    db.commit()
    return {"medications_created": created, "medications_updated": updated}


# ── Vitals sync ───────────────────────────────────────────────────────────────

def sync_vitals(client: FHIRClient, db: Session, fhir_patient_id: str,
                patient_db_id: uuid.UUID) -> dict:
    """Group vital-sign Observations by date and upsert PatientVital records."""
    vitals_by_date: dict[str, dict] = {}

    for res in client.paginate("Observation", {
        "patient": fhir_patient_id,
        "category": "vital-signs",
    }):
        effective = res.get("effectiveDateTime", "")[:10]
        if not effective:
            continue

        loinc = _coding_value(res.get("code", {}), "loinc.org")
        field = VITAL_LOINC_MAP.get(loinc)
        if not field:
            continue

        value_qty = res.get("valueQuantity", {})
        raw_value = value_qty.get("value")
        if raw_value is None:
            continue

        if effective not in vitals_by_date:
            vitals_by_date[effective] = {"recorded_at": _parse_datetime(res.get("effectiveDateTime"))}
        vitals_by_date[effective][field] = raw_value

    created = 0
    for date_str, fields in vitals_by_date.items():
        recorded_at = fields.pop("recorded_at", None)
        # Check if vital for this patient/date already exists
        existing = db.query(PatientVital).filter(
            PatientVital.patient_id == patient_db_id,
            PatientVital.recorded_at >= datetime.fromisoformat(f"{date_str}T00:00:00+00:00"),
        ).first() if recorded_at else None

        if not existing:
            vital = PatientVital(patient_id=patient_db_id, recorded_at=recorded_at, **fields)
            db.add(vital)
            created += 1

    db.commit()
    return {"vitals_created": created}


# ── Labs sync ─────────────────────────────────────────────────────────────────

def sync_labs(client: FHIRClient, db: Session, fhir_patient_id: str,
              patient_db_id: uuid.UUID) -> dict:
    created = 0

    for res in client.paginate("Observation", {
        "patient": fhir_patient_id,
        "category": "laboratory",
    }):
        fhir_obs_id = res.get("id")
        if db.query(PatientLab).filter_by(fhir_observation_id=fhir_obs_id).first():
            continue

        code_block = res.get("code", {})
        test_name = code_block.get("text") or (
            code_block.get("coding", [{}])[0].get("display")
        ) or "Unknown"
        loinc_code = _coding_value(code_block, "loinc.org")

        value_qty = res.get("valueQuantity", {})
        result_value = str(value_qty.get("value", "")) if value_qty else res.get("valueString")
        result_unit = value_qty.get("unit")
        ref_range = res.get("referenceRange", [{}])[0].get("text")
        is_abnormal = bool(res.get("interpretation"))

        collected = _parse_datetime(res.get("effectiveDateTime"))

        lab = PatientLab(
            patient_id=patient_db_id,
            test_name=test_name[:255],
            loinc_code=loinc_code,
            result_value=result_value,
            result_unit=result_unit,
            reference_range=ref_range,
            is_abnormal=is_abnormal,
            collected_at=collected,
            fhir_observation_id=fhir_obs_id,
        )
        db.add(lab)
        created += 1

    db.commit()
    return {"labs_created": created}


# ── CPT codes from Procedures ─────────────────────────────────────────────────

def sync_procedures_as_cpt(client: FHIRClient, db: Session, fhir_patient_id: str) -> dict:
    upserted = 0
    for res in client.paginate("Procedure", {"patient": fhir_patient_id}):
        code_block = res.get("code", {})
        cpt_code = _coding_value(code_block, "cpt") or _coding_value(code_block, "http://www.ama-assn.org")
        if not cpt_code:
            # Try generic coding — 5-digit numeric = CPT
            for c in code_block.get("coding", []):
                if c.get("code", "").isdigit() and len(c["code"]) == 5:
                    cpt_code = c["code"]
                    break
        if not cpt_code:
            continue

        description = (
            code_block.get("text")
            or code_block.get("coding", [{}])[0].get("display")
            or cpt_code
        )
        if not db.query(CptCode).filter_by(code=cpt_code).first():
            db.add(CptCode(
                code=cpt_code,
                description=description[:500],
                short_description=description[:100],
                is_active=True,
            ))
            upserted += 1

    db.commit()
    return {"cpt_from_procedures": upserted}


# ── Full patient sync ─────────────────────────────────────────────────────────

def sync_patient_full(client: FHIRClient, db: Session, fhir_patient_id: str,
                      org_id: uuid.UUID) -> dict:
    """Sync all clinical data for one FHIR patient."""
    patient = db.query(Patient).filter_by(fhir_patient_id=fhir_patient_id).first()
    if not patient:
        # Fetch and create the patient first
        res = client.get(f"Patient/{fhir_patient_id}")
        summary = sync_patients.__wrapped__ if hasattr(sync_patients, "__wrapped__") else None
        # Manual single-patient sync
        from app.integrations.fhir.sync import _single_patient_upsert
        patient = _single_patient_upsert(res, db, org_id)
        if not patient:
            return {"error": f"Patient {fhir_patient_id} not found or invalid"}

    result = {}
    result.update(sync_conditions(client, db, fhir_patient_id, patient.id))
    result.update(sync_medications(client, db, fhir_patient_id, patient.id))
    result.update(sync_vitals(client, db, fhir_patient_id, patient.id))
    result.update(sync_labs(client, db, fhir_patient_id, patient.id))
    result.update(sync_procedures_as_cpt(client, db, fhir_patient_id))
    return result


def _single_patient_upsert(res: dict, db: Session, org_id: uuid.UUID) -> Optional[Patient]:
    fhir_id = res.get("id")
    if not fhir_id:
        return None
    names = res.get("name", [])
    name = next((n for n in names if n.get("use") == "official"), names[0] if names else {})
    last_name = name.get("family") or "Unknown"
    given = name.get("given", [])
    first_name = given[0] if given else "Unknown"
    dob = _parse_date(res.get("birthDate"))
    if not dob:
        return None
    gender = _map_gender(res.get("gender", "unknown"))
    telecom = res.get("telecom", [])
    phone = next((t["value"] for t in telecom if t.get("system") == "phone"), None)
    email = next((t["value"] for t in telecom if t.get("system") == "email"), None)
    addrs = res.get("address", [])
    addr = addrs[0] if addrs else {}
    lines = addr.get("line", [])
    mrn = f"FHIR-{fhir_id}"

    existing = db.query(Patient).filter(
        (Patient.fhir_patient_id == fhir_id) | (Patient.mrn == mrn)
    ).first()
    if existing:
        existing.fhir_patient_id = fhir_id
        db.commit()
        return existing

    patient = Patient(
        organization_id=org_id,
        mrn=mrn,
        fhir_patient_id=fhir_id,
        first_name=first_name,
        last_name=last_name,
        date_of_birth=dob,
        gender=gender,
        phone=phone,
        email=email,
        address_line1=lines[0] if lines else None,
        city=addr.get("city"),
        state=addr.get("state"),
        zip=addr.get("postalCode"),
    )
    db.add(patient)
    db.commit()
    return patient
