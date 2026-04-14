"""
SMART Health IT FHIR R4 integration endpoints.

Uses the public sandbox at https://r4.smarthealthit.org — no credentials needed.

Endpoints:
  GET  /api/fhir/status                        → server capability
  POST /api/fhir/sync/patients                 → sync batch of patients
  POST /api/fhir/sync/patient/{fhir_id}        → sync one patient + all clinical data
  GET  /api/fhir/search/patients               → live search on FHIR server
  GET  /api/fhir/search/conditions             → live ICD-10 condition search
"""
from fastapi import FastAPI, APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from common.config import settings
from common.security import get_current_user
from common.db import get_db
from common.integrations.fhir.client import FHIRClient
from common.integrations.fhir.sync import (
    sync_patients, sync_patient_full, sync_conditions,
    sync_medications, sync_vitals, sync_labs,
)

app = FastAPI(title="FHIR Service")
router = APIRouter()


def _client() -> FHIRClient:
    return FHIRClient(settings.SMART_FHIR_BASE_URL)


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status", summary="Check FHIR server connectivity")
async def fhir_status():
    try:
        cap = _client().capability()
        return {
            "connected": True,
            "server": settings.SMART_FHIR_BASE_URL,
            "fhir_version": cap.get("fhirVersion"),
            "software": cap.get("software", {}).get("name"),
        }
    except Exception as exc:
        return {"connected": False, "error": str(exc)}


# ── Sync patients batch ───────────────────────────────────────────────────────

@router.post("/sync/patients", summary="Sync a batch of FHIR patients into OneClick")
async def sync_fhir_patients(
    limit: int = Query(50, ge=1, le=200, description="Max patients to sync"),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.get("role") not in ("admin", "super_admin", "provider"):
        raise HTTPException(status_code=403, detail="Provider or admin access required")

    org_id = uuid.UUID(str(current_user["org_id"]))
    client = _client()
    try:
        result = sync_patients(client, db, org_id, limit=limit)
    except Exception as exc:
        import traceback
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    return {"status": "completed", "server": settings.SMART_FHIR_BASE_URL, **result}


# ── Sync single patient (full clinical data) ──────────────────────────────────

@router.post("/sync/patient/{fhir_patient_id}", summary="Sync one patient + conditions, meds, vitals, labs")
async def sync_single_patient(
    fhir_patient_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.get("role") not in ("admin", "super_admin", "provider"):
        raise HTTPException(status_code=403, detail="Provider or admin access required")

    org_id = uuid.UUID(str(current_user["org_id"]))
    client = _client()
    result = sync_patient_full(client, db, fhir_patient_id, org_id)
    return {"status": "completed", "fhir_patient_id": fhir_patient_id, **result}


# ── Live search ───────────────────────────────────────────────────────────────

@router.get("/search/patients", summary="Live patient search on FHIR server")
async def search_fhir_patients(
    name: str = Query(None, description="Search by name"),
    family: str = Query(None, description="Search by last name"),
    birthdate: str = Query(None, description="Filter by DOB (YYYY-MM-DD)"),
    limit: int = Query(20, le=50),
    current_user=Depends(get_current_user),
):
    client = _client()
    params = {"_count": str(limit)}
    if name:
        params["name"] = name
    if family:
        params["family"] = family
    if birthdate:
        params["birthdate"] = birthdate

    results = []
    for res in client.paginate("Patient", params):
        names = res.get("name", [])
        name_obj = names[0] if names else {}
        given = name_obj.get("given", [])
        results.append({
            "fhir_id": res.get("id"),
            "first_name": given[0] if given else None,
            "last_name": name_obj.get("family"),
            "dob": res.get("birthDate"),
            "gender": res.get("gender"),
        })
        if len(results) >= limit:
            break

    return {"total": len(results), "server": settings.SMART_FHIR_BASE_URL, "patients": results}


@router.get("/search/conditions", summary="Live ICD-10 condition search on FHIR server")
async def search_fhir_conditions(
    patient_fhir_id: str = Query(..., description="FHIR patient ID"),
    current_user=Depends(get_current_user),
):
    client = _client()
    conditions = []
    for res in client.paginate("Condition", {"patient": patient_fhir_id}):
        code_block = res.get("code", {})
        codings = code_block.get("coding", [])
        icd_coding = next(
            (c for c in codings if "icd" in c.get("system", "").lower()),
            codings[0] if codings else {}
        )
        conditions.append({
            "fhir_id": res.get("id"),
            "icd10_code": icd_coding.get("code"),
            "description": icd_coding.get("display") or code_block.get("text"),
            "status": res.get("clinicalStatus", {}).get("coding", [{}])[0].get("code"),
            "onset": res.get("onsetDateTime", "")[:10] or None,
        })

    return {
        "patient_fhir_id": patient_fhir_id,
        "total": len(conditions),
        "conditions": conditions,
    }


@router.get("/search/medications", summary="Live medication search on FHIR server")
async def search_fhir_medications(
    patient_fhir_id: str = Query(..., description="FHIR patient ID"),
    current_user=Depends(get_current_user),
):
    client = _client()
    meds = []
    for res in client.paginate("MedicationRequest", {"patient": patient_fhir_id}):
        med_block = res.get("medicationCodeableConcept", {})
        codings = med_block.get("coding", [])
        rxnorm = next((c for c in codings if "rxnorm" in c.get("system", "").lower()), {})
        meds.append({
            "fhir_id": res.get("id"),
            "name": med_block.get("text") or rxnorm.get("display"),
            "rxnorm_code": rxnorm.get("code"),
            "status": res.get("status"),
            "dosage": res.get("dosageInstruction", [{}])[0].get("text"),
        })

    return {"patient_fhir_id": patient_fhir_id, "total": len(meds), "medications": meds}
app.include_router(router)
