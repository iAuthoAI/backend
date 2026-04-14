from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from datetime import date, datetime
from common.db import get_db
from patient.patient_models import Patient, PatientCoverage, PatientProblem, PatientMedication, PatientLab, PatientVital, Appointment, ClinicalNote
from common.security import get_current_user

app = FastAPI()

def _build_patient_payload(p, db, room="", chief_complaint="", status="", provider_name=""):
    # Simplified version for now
    return {
        "id": str(p.id),
        "name": p.full_name,
        "mrn": p.mrn,
        "first_name": p.first_name,
        "last_name": p.last_name,
        "dob": p.date_of_birth.isoformat() if p.date_of_birth else None,
        "gender": p.gender,
        "room": room,
        "chiefComplaint": chief_complaint,
        "status": status,
        "provider": provider_name,
    }

@app.get("/")
async def list_patients(
    search: Optional[str] = None,
    limit: int = Query(20, le=100),
    offset: int = 0,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Patient).filter(Patient.is_active == True)
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            (Patient.first_name.ilike(search_term)) |
            (Patient.last_name.ilike(search_term)) |
            (Patient.mrn.ilike(search_term))
        )
    total = query.count()
    patients = query.order_by(Patient.last_name, Patient.first_name).offset(offset).limit(limit).all()

    today = date.today()
    result = []
    for p in patients:
        appt = db.query(Appointment).filter(
            Appointment.patient_id == str(p.id),
            Appointment.scheduled_time >= datetime.combine(today, datetime.min.time()),
            Appointment.scheduled_time < datetime.combine(today, datetime.max.time()),
        ).order_by(Appointment.scheduled_time).first()

        payload = _build_patient_payload(
            p, db,
            room=appt.room if appt else "",
            chief_complaint=appt.chief_complaint if appt else "",
            status=appt.appointment_type if appt else "",
            provider_name=f"Dr. {p.last_name}",
        )
        result.append(payload)

    return {
        "total": total,
        "patients": result,
    }

@app.get("/{patient_id}")
async def get_patient(patient_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    patient = db.query(Patient).options(
        joinedload(Patient.coverage).joinedload(PatientCoverage.payer),
        joinedload(Patient.coverage).joinedload(PatientCoverage.plan),
        joinedload(Patient.problems),
        joinedload(Patient.medications),
    ).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    latest_vitals = db.query(PatientVital).filter(
        PatientVital.patient_id == patient_id
    ).order_by(PatientVital.recorded_at.desc()).first()

    recent_labs = db.query(PatientLab).filter(
        PatientLab.patient_id == patient_id
    ).order_by(PatientLab.resulted_at.desc()).limit(10).all()

    recent_notes = db.query(ClinicalNote).filter(
        ClinicalNote.patient_id == patient_id
    ).order_by(ClinicalNote.created_at.desc()).limit(5).all()

    return {
        "id": str(patient.id),
        "mrn": patient.mrn,
        "fhir_patient_id": patient.fhir_patient_id,
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "full_name": patient.full_name,
        "date_of_birth": patient.date_of_birth.isoformat() if patient.date_of_birth else None,
        "gender": patient.gender,
        "phone": patient.phone,
        "email": patient.email,
        "address": {
            "line1": patient.address_line1,
            "line2": patient.address_line2,
            "city": patient.city,
            "state": patient.state,
            "zip": patient.zip,
        },
        "allergies": patient.allergies,
        "code_status": patient.code_status,
        "coverage": [
            {
                "id": str(c.id),
                "coverage_order": c.coverage_order,
                "payer_name": c.payer.name if c.payer else None,
                "payer_code": c.payer.code if c.payer else None,
                "plan_name": c.plan.name if c.plan else None,
                "plan_type": c.plan.plan_type if c.plan else None,
                "member_id": c.member_id,
                "group_number": c.group_number,
                "copay": float(c.copay) if c.copay else None,
                "effective_date": c.effective_date.isoformat() if c.effective_date else None,
                "is_active": c.is_active,
                "is_selected_for_pa": c.is_selected_for_pa,
            }
            for c in sorted(patient.coverage, key=lambda x: x.coverage_order)
        ],
        "active_problems": [
            {"icd10_code": p.icd10_code, "problem_name": p.problem_name, "status": p.status}
            for p in patient.problems if p.status == "active"
        ],
        "medications": [
            {"name": m.medication_name, "dose": m.dose, "route": m.route, "frequency": m.frequency}
            for m in patient.medications if m.is_active
        ],
        "latest_vitals": {
            "bp": f"{latest_vitals.bp_systolic}/{latest_vitals.bp_diastolic}" if latest_vitals else None,
            "hr": latest_vitals.heart_rate if latest_vitals else None,
            "temp": float(latest_vitals.temperature) if latest_vitals and latest_vitals.temperature else None,
            "rr": latest_vitals.respiratory_rate if latest_vitals else None,
            "spo2": latest_vitals.spo2 if latest_vitals else None,
            "recorded_at": latest_vitals.recorded_at.isoformat() if latest_vitals else None,
        } if latest_vitals else None,
        "recent_labs": [
            {
                "test_name": lab.test_name,
                "result_value": lab.result_value,
                "result_unit": lab.result_unit,
                "reference_range": lab.reference_range,
                "is_abnormal": lab.is_abnormal,
                "abnormal_flag": lab.abnormal_flag,
                "resulted_at": lab.resulted_at.isoformat() if lab.resulted_at else None,
            }
            for lab in recent_labs
        ],
        "recent_notes": [
            {
                "id": str(n.id),
                "note_type": n.note_type,
                "title": n.title,
                "author_id": str(n.author_id),
                "excerpt": n.content[:100] + "..." if len(n.content) > 100 else n.content,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in recent_notes
        ],
    }

@app.get("/{patient_id}/schedule")
async def get_patient_schedule(patient_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    appointments = db.query(Appointment).options(
        joinedload(Appointment.patient)
    ).filter(
        Appointment.patient_id == patient_id
    ).order_by(Appointment.scheduled_time).all()

    return [
        {
            "id": str(a.id),
            "appointment_type": a.appointment_type,
            "scheduled_time": a.scheduled_time.isoformat(),
            "room": a.room,
            "chief_complaint": a.chief_complaint,
            "status": a.status,
        }
        for a in appointments
    ]
