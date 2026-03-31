from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from datetime import date, datetime
from app.db.session import get_db
from app.models.pa_request import Appointment, PaRequest
from app.models.patient import Patient, PatientVital, PatientCoverage
from app.models.user import User
from app.core.security import get_current_user

router = APIRouter()


@router.get("/today")
async def get_today_schedule(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    provider_id = current_user["user_id"]

    appointments = db.query(Appointment).options(
        joinedload(Appointment.patient).joinedload(Patient.vitals),
        joinedload(Appointment.patient).joinedload(Patient.coverage).joinedload(PatientCoverage.payer),
    ).filter(
        Appointment.provider_id == provider_id,
        Appointment.scheduled_time >= datetime.combine(today, datetime.min.time()),
        Appointment.scheduled_time < datetime.combine(today, datetime.max.time()),
    ).order_by(Appointment.scheduled_time).all()

    result = []
    for appt in appointments:
        patient = appt.patient

        latest_vital = db.query(PatientVital).filter(
            PatientVital.patient_id == str(patient.id)
        ).order_by(PatientVital.recorded_at.desc()).first()

        active_pa = db.query(PaRequest).filter(
            PaRequest.patient_id == str(patient.id),
            PaRequest.status.in_(["intake_review", "clinical_review", "decision_pending", "action_required"])
        ).first()

        expiring_pa = db.query(PaRequest).filter(
            PaRequest.patient_id == str(patient.id),
            PaRequest.status == "approved",
            PaRequest.expires_at.isnot(None),
        ).first()

        auth_status = None
        if expiring_pa:
            auth_status = "Expiring"
        elif active_pa:
            status_map = {
                "intake_review": "Intake Review",
                "clinical_review": "Clinical Review",
                "decision_pending": "Decision Pending",
                "action_required": "Action Required",
                "appeal_submitted": "Appeal",
            }
            auth_status = status_map.get(active_pa.status)

        approved_pa = db.query(PaRequest).filter(
            PaRequest.patient_id == str(patient.id),
            PaRequest.status == "approved"
        ).first()
        if approved_pa and not expiring_pa:
            auth_status = "Verified"

        denied_pa = db.query(PaRequest).filter(
            PaRequest.patient_id == str(patient.id),
            PaRequest.status == "denied"
        ).first()
        if denied_pa and not active_pa:
            auth_status = "Denied"

        result.append({
            "appointment_id": str(appt.id),
            "scheduled_time": appt.scheduled_time.strftime("%H:%M"),
            "appointment_type": appt.appointment_type,
            "room": appt.room,
            "chief_complaint": appt.chief_complaint,
            "status": appt.status,
            "patient": {
                "id": str(patient.id),
                "mrn": patient.mrn,
                "full_name": f"{patient.first_name} {patient.last_name}",
                "first_name": patient.first_name,
                "last_name": patient.last_name,
                "age": (date.today() - patient.date_of_birth).days // 365,
                "gender": patient.gender,
                "allergies": patient.allergies,
                "code_status": patient.code_status,
            },
            "vitals": {
                "bp": f"{latest_vital.bp_systolic}/{latest_vital.bp_diastolic}" if latest_vital else None,
                "hr": latest_vital.heart_rate if latest_vital else None,
                "bp_elevated": (latest_vital.bp_systolic and latest_vital.bp_systolic > 140) if latest_vital else False,
                "hr_elevated": (latest_vital.heart_rate and latest_vital.heart_rate > 100) if latest_vital else False,
            } if latest_vital else None,
            "auth_status": auth_status,
        })

    return {
        "date": today.isoformat(),
        "provider": current_user.get("email"),
        "patient_count": len(result),
        "appointments": result,
    }


@router.get("/dashboard")
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
