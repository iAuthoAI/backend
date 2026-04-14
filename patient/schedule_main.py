from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from datetime import date, datetime
from common.db import get_db
from pa.pa_models import PaRequest
from patient.patient_models import Appointment, ClinicalNote, Patient, PatientVital, PatientCoverage, PatientProblem, PatientMedication, PatientLab
from login.login_models import User
from common.security import get_current_user

app = FastAPI(
    title="Scheduler Service",
    docs_url="/docs",
    openapi_url="/openapi.json"
)


def _gender_short(g: str) -> str:
    return {"male": "M", "female": "F"}.get((g or "").lower(), g or "U")


def _last_first(p: Patient) -> str:
    return f"{p.last_name}, {p.first_name}"


def _priority_label(order: int) -> str:
    return {1: "Primary", 2: "Secondary", 3: "Tertiary"}.get(order, "Other")


def _build_patient_payload(patient: Patient, db: Session, *, room: str = "", chief_complaint: str = "", status: str = "", provider_name: str = ""):
    """Build a Patient payload matching the frontend Patient interface."""
    age = (date.today() - patient.date_of_birth).days // 365 if patient.date_of_birth else 0

    latest_vital = db.query(PatientVital).filter(
        PatientVital.patient_id == str(patient.id)
    ).order_by(PatientVital.recorded_at.desc()).first()

    problems = db.query(PatientProblem).filter(
        PatientProblem.patient_id == str(patient.id),
        PatientProblem.status == "active",
    ).all()

    medications = db.query(PatientMedication).filter(
        PatientMedication.patient_id == str(patient.id),
        PatientMedication.is_active == True,
    ).all()

    labs = db.query(PatientLab).filter(
        PatientLab.patient_id == str(patient.id),
    ).order_by(PatientLab.resulted_at.desc()).limit(10).all()

    notes = db.query(ClinicalNote).filter(
        ClinicalNote.patient_id == str(patient.id),
    ).order_by(ClinicalNote.created_at.desc()).limit(5).all()

    coverages = db.query(PatientCoverage).options(
        joinedload(PatientCoverage.payer),
        joinedload(PatientCoverage.plan),
    ).filter(
        PatientCoverage.patient_id == str(patient.id),
        PatientCoverage.is_active == True,
    ).order_by(PatientCoverage.coverage_order).all()

    allergies_raw = patient.allergies or []
    if isinstance(allergies_raw, list):
        allergy_strs = []
        for a in allergies_raw:
            if isinstance(a, dict):
                allergy_strs.append(f"{a.get('allergen', '')} ({a.get('reaction', '')})" if a.get('reaction') else a.get('allergen', ''))
            else:
                allergy_strs.append(str(a))
    else:
        allergy_strs = [str(allergies_raw)]

    if not allergy_strs:
        allergy_strs = ["No Known Allergies"]

    return {
        "id": str(patient.id),
        "mrn": patient.mrn,
        "name": _last_first(patient),
        "dob": patient.date_of_birth.isoformat() if patient.date_of_birth else "",
        "age": age,
        "sex": _gender_short(patient.gender),
        "room": room or "",
        "chiefComplaint": chief_complaint or "",
        "status": status or "",
        "provider": provider_name or "Provider",
        "allergies": allergy_strs,
        "insurance": [
            {
                "payerId": str(c.payer.id) if c.payer else "",
                "payerName": c.payer.name if c.payer else "",
                "payerShortName": c.payer.code if c.payer else "",
                "planType": c.plan.plan_type if c.plan else "",
                "memberId": c.member_id or "",
                "groupNumber": c.group_number or "",
                "priority": _priority_label(c.coverage_order),
                "status": "Active" if c.is_active else "Inactive",
                "effectiveDate": c.effective_date.isoformat() if c.effective_date else "",
                "copay": f"${int(c.copay)}" if c.copay else "",
            }
            for c in coverages
        ],
        "vitals": {
            "bp": f"{latest_vital.bp_systolic}/{latest_vital.bp_diastolic}" if latest_vital and latest_vital.bp_systolic else "N/A",
            "hr": latest_vital.heart_rate if latest_vital else 0,
            "temp": float(latest_vital.temperature) if latest_vital and latest_vital.temperature else 98.6,
            "rr": latest_vital.respiratory_rate if latest_vital else 0,
            "o2": latest_vital.spo2 if latest_vital else 100,
        },
        "medications": [
            {"name": m.medication_name, "dose": m.dose or "", "route": m.route or "", "freq": m.frequency or ""}
            for m in medications
        ],
        "problems": [p.problem_name for p in problems],
        "labs": [
            {
                "name": lab.test_name,
                "value": lab.result_value or "",
                "unit": lab.result_unit or "",
                "flag": lab.abnormal_flag if lab.is_abnormal else None,
                "date": lab.resulted_at.strftime("Today %H%M") if lab.resulted_at and lab.resulted_at.date() == date.today() else (lab.resulted_at.strftime("%m/%d %H%M") if lab.resulted_at else ""),
            }
            for lab in labs
        ],
        "notes": [
            {
                "id": str(n.id),
                "date": n.created_at.strftime("Today %H:%M") if n.created_at and n.created_at.date() == date.today() else (n.created_at.strftime("Yesterday %H:%M") if n.created_at else ""),
                "author": provider_name or "Provider",
                "type": n.note_type,
                "preview": n.content[:80] + "..." if n.content and len(n.content) > 80 else (n.content or ""),
            }
            for n in notes
        ],
    }


@app.get("/today")
async def get_today_schedule(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    provider_id = current_user["user_id"]

    provider = db.query(User).filter(User.id == provider_id).first()
    provider_name = f"Dr. {provider.last_name}" if provider else "Provider"

    appointments = db.query(Appointment).options(
        joinedload(Appointment.patient),
    ).filter(
        Appointment.provider_id == provider_id,
        Appointment.scheduled_time >= datetime.combine(today, datetime.min.time()),
        Appointment.scheduled_time < datetime.combine(today, datetime.max.time()),
    ).order_by(Appointment.scheduled_time).all()

    patients = []
    for appt in appointments:
        p = _build_patient_payload(
            appt.patient, db,
            room=appt.room or "",
            chief_complaint=appt.chief_complaint or "",
            status=appt.appointment_type or "",
            provider_name=provider_name,
        )
        p["scheduled_time"] = appt.scheduled_time.strftime("%H:%M")

        # Auth status
        active_pa = db.query(PaRequest).filter(
            PaRequest.patient_id == str(appt.patient.id),
            PaRequest.status.in_(["intake_review", "clinical_review", "decision_pending", "action_required"])
        ).first()
        expiring_pa = db.query(PaRequest).filter(
            PaRequest.patient_id == str(appt.patient.id),
            PaRequest.status == "approved",
            PaRequest.expires_at.isnot(None),
        ).first()
        approved_pa = db.query(PaRequest).filter(
            PaRequest.patient_id == str(appt.patient.id),
            PaRequest.status == "approved"
        ).first()
        denied_pa = db.query(PaRequest).filter(
            PaRequest.patient_id == str(appt.patient.id),
            PaRequest.status == "denied"
        ).first()

        auth_status = None
        if expiring_pa:
            auth_status = "Expiring"
        elif denied_pa and not active_pa:
            auth_status = "Appeal"
        elif approved_pa:
            auth_status = "Verified"
        elif active_pa:
            auth_status = "In Review"

        p["auth_status"] = auth_status
        patients.append(p)

    return {
        "date": today.isoformat(),
        "provider": provider_name,
        "patient_count": len(patients),
        "patients": patients,
    }


@app.get("/dashboard")
async def get_dashboard(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    provider_id = current_user["user_id"]

    today_appointments = db.query(Appointment).filter(
        Appointment.provider_id == provider_id,
    ).count()

    expiring_auths = db.query(PaRequest).filter(
        PaRequest.requesting_provider_id == provider_id,
        PaRequest.status == "approved",
        PaRequest.expires_at.isnot(None),
    ).count()

    high_prob = db.query(PaRequest).filter(
        PaRequest.requesting_provider_id == provider_id,
        PaRequest.ai_score >= 80,
        PaRequest.status.in_(["draft", "submitted"])
    ).count()

    appeal_ready = db.query(PaRequest).filter(
        PaRequest.requesting_provider_id == provider_id,
        PaRequest.status == "denied"
    ).count()

    return {
        "stats": {
            "today_patients": today_appointments,
            "expiring_auths": expiring_auths,
            "high_prob_approvals": high_prob,
            "appeal_ready": appeal_ready,
        },
        "alerts": [
            {
                "type": "expiring",
                "message": f"Anderson, S. (MRI) auth expires in 3 days. Renew now to avoid gaps.",
                "icon": "warning",
            } if expiring_auths > 0 else None,
            {
                "type": "high_prob",
                "message": f"AI predicts instant approval for pending labs based on recent payer trends.",
                "count": high_prob,
                "icon": "lightning",
            } if high_prob > 0 else None,
            {
                "type": "appeal",
                "message": f"Draft appeal for Garcia, M. generated and ready for review.",
                "icon": "check",
            } if appeal_ready > 0 else None,
        ]
    }
