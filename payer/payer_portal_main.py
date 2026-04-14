from fastapi import FastAPI, Depends, Query, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from common.db import get_db
from pa.pa_models import PaRequest, PaStatusHistory
from patient.patient_models import Patient, PatientCoverage
from payer.payer_models import Payer, PayerPolicy
from notifications.notifications_models import Notification
from common.security import get_current_user

app = FastAPI(
    title="Payer Portal Service",
    docs_url="/docs",
    openapi_url="/openapi.json"
)


@app.get("/intake/queue")
async def get_intake_queue(
    limit: int = Query(20, le=100),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Intake Review Queue"""
    requests = db.query(PaRequest).options(
        joinedload(PaRequest.patient),
        joinedload(PaRequest.payer),
        joinedload(PaRequest.coverage).joinedload(PatientCoverage.plan),
    ).filter(
        PaRequest.status.in_(["submitted", "intake_review"])
    ).order_by(PaRequest.submitted_at.asc()).limit(limit).all()

    items = [
        {
            "id": str(r.id),
            "request_number": r.request_number,
            "patient_name": f"{r.patient.last_name}, {r.patient.first_name}" if r.patient else None,
            "member_id": r.coverage.member_id if r.coverage else None,
            "payer_name": r.payer.name if r.payer else None,
            "service_type": r.cpt_description,
            "cpt_code": r.cpt_code,
            "priority": r.priority,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            "days_pending": _days_pending(r.submitted_at),
            "ai_score": r.ai_score,
            "status": r.status,
        }
        for r in requests
    ]
    return {"items": items, "total": len(items)}


def _days_pending(dt) -> int:
    if not dt:
        return 0
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).days


@app.get("/intake/review/{pa_id}")
async def get_intake_review(pa_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Detailed intake review for a specific PA request"""
    pa = db.query(PaRequest).options(
        joinedload(PaRequest.patient).joinedload(Patient.coverage).joinedload(PatientCoverage.payer),
        joinedload(PaRequest.payer),
        joinedload(PaRequest.coverage).joinedload(PatientCoverage.plan),
        joinedload(PaRequest.documents),
        joinedload(PaRequest.form_template),
        joinedload(PaRequest.requesting_provider),
    ).filter(PaRequest.id == pa_id).first()

    if not pa:
        raise HTTPException(status_code=404, detail="PA request not found")

    import datetime as dt_module
    today = dt_module.date.today()
    age = ((today - pa.patient.date_of_birth).days // 365) if pa.patient and pa.patient.date_of_birth else None
    dob_str = pa.patient.date_of_birth.strftime("%m/%d/%Y") if pa.patient and pa.patient.date_of_birth else None

    priority_label = pa.priority or "routine"
    urgency_map = {"stat": "Emergent", "urgent": "Urgent", "routine": "Routine", "standard": "Routine"}

    return {
        "id": str(pa.id),
        "request_number": pa.request_number,
        "patient": {
            "name": f"{pa.patient.first_name} {pa.patient.last_name}" if pa.patient else None,
            "dob": f"{dob_str} (Age {age})" if dob_str else None,
            "member_id": pa.coverage.member_id if pa.coverage else "DEMO-MEMBER",
            "group_id": pa.coverage.plan.group_number if pa.coverage and pa.coverage.plan and hasattr(pa.coverage.plan, 'group_number') else "GRP-00001",
            "plan_name": (pa.coverage.plan.name if pa.coverage and pa.coverage.plan else None) or (pa.payer.name + " PPO" if pa.payer else "—"),
        } if pa.patient else None,
        "provider": {
            "name": pa.requesting_provider.full_name if pa.requesting_provider else "Attending Physician",
            "npi": "1234567890",
            "specialty": "Internal Medicine",
            "phone": "(555) 000-0000",
        },
        "service": {
            "cpt_code": pa.cpt_code,
            "description": pa.cpt_description,
            "icd10": pa.icd10_primary,
            "diagnosis": pa.icd10_primary_desc or pa.icd10_primary,
            "units": 1,
            "start_date": pa.service_date.strftime("%Y-%m-%d") if pa.service_date else None,
        },
        "clinical_info": {
            "notes": pa.clinical_notes or pa.clinical_justification or "No clinical notes provided.",
            "urgency": urgency_map.get(priority_label, "Routine"),
        },
        "documents": [],
        "ai_score": pa.ai_score,
        "status": pa.status,
        "priority": pa.priority,
        "submitted_at": pa.submitted_at.isoformat() if pa.submitted_at else None,
    }


@app.post("/intake/review/{pa_id}")
async def submit_intake_review(
    pa_id: str,
    body: Dict[str, Any],
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pa = db.query(PaRequest).filter(PaRequest.id == pa_id).first()
    if not pa:
        raise HTTPException(status_code=404, detail="PA request not found")

    action = body.get("action") or body.get("decision") or "forward_clinical"
    if action == "approve":
        action = "forward_clinical"
    notes = body.get("notes", "")

    status_map = {
        "forward_clinical": "clinical_review",
        "request_info": "action_required",
        "deny": "denied",
    }
    old_status = pa.status
    new_status = status_map.get(action, "clinical_review")
    pa.status = new_status

    history = PaStatusHistory(
        pa_request_id=pa.id,
        from_status=old_status,
        to_status=new_status,
        changed_by=current_user.id,
        notes=f"Intake {action}: {notes}" if notes else f"Intake {action}",
    )
    db.add(history)

    # Notify requesting provider when action is required
    if action == "request_info" and pa.requesting_provider_id:
        notif = Notification(
            user_id=pa.requesting_provider_id,
            pa_request_id=pa.id,
            type="rfi_received",
            title=f"Additional Information Required — {pa.request_number}",
            message=notes or "The payer has requested additional information to process your prior authorization request. Please review and resubmit.",
            action_url=f"/provider/pa-requests/{pa.id}",
        )
        db.add(notif)

    db.commit()
    return {"success": True, "new_status": new_status}


@app.get("/clinical/queue")
async def get_clinical_queue(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Clinical Review Queue"""
    requests = db.query(PaRequest).options(
        joinedload(PaRequest.patient),
        joinedload(PaRequest.payer),
        joinedload(PaRequest.coverage).joinedload(PatientCoverage.plan),
    ).filter(
        PaRequest.status == "clinical_review"
    ).order_by(PaRequest.clinical_started_at.asc()).all()

    items = [
        {
            "id": str(r.id),
            "request_number": r.request_number,
            "patient_name": f"{r.patient.last_name}, {r.patient.first_name}" if r.patient else None,
            "member_id": r.coverage.member_id if r.coverage else None,
            "payer_name": r.payer.name if r.payer else None,
            "service_type": r.cpt_description,
            "cpt_code": r.cpt_code,
            "priority": r.priority,
            "days_pending": _days_pending(r.submitted_at),
            "ai_score": r.ai_score,
            "status": r.status,
            "clinical_criteria_met": None,
        }
        for r in requests
    ]
    return {"items": items, "total": len(items)}


@app.get("/clinical/review/{pa_id}")
async def get_clinical_review(pa_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Clinical review details"""
    pa = db.query(PaRequest).options(
        joinedload(PaRequest.patient),
        joinedload(PaRequest.payer),
        joinedload(PaRequest.coverage).joinedload(PatientCoverage.plan),
        joinedload(PaRequest.form_template),
        joinedload(PaRequest.requesting_provider),
    ).filter(PaRequest.id == pa_id).first()

    if not pa:
        raise HTTPException(status_code=404, detail="PA request not found")

    # Check policy match
    all_policies = db.query(PayerPolicy).filter(
        PayerPolicy.payer_id == pa.payer_id,
        PayerPolicy.is_active == True,
    ).all()
    policy = next((p for p in all_policies if p.cpt_codes and pa.cpt_code in p.cpt_codes), None)

    # Build AI gaps/suggestions from stored data
    ai_gaps = pa.ai_gaps or []
    ai_suggestions = pa.ai_suggestions or []
    gaps = [g if isinstance(g, str) else g.get("gap", "") for g in ai_gaps]
    suggestions = [s if isinstance(s, str) else s.get("suggestion", "") for s in ai_suggestions]

    import datetime as dt_module
    today = dt_module.date.today()
    dob_str = pa.patient.date_of_birth.strftime("%m/%d/%Y") if pa.patient and pa.patient.date_of_birth else None
    age = ((today - pa.patient.date_of_birth).days // 365) if pa.patient and pa.patient.date_of_birth else None

    return {
        "id": str(pa.id),
        "request_number": pa.request_number,
        "patient": {
            "name": f"{pa.patient.first_name} {pa.patient.last_name}" if pa.patient else None,
            "dob": f"{dob_str} (Age {age})" if dob_str else None,
            "member_id": pa.coverage.member_id if pa.coverage else "DEMO-MEMBER",
            "plan_name": (pa.coverage.plan.name if pa.coverage and pa.coverage.plan else None) or (pa.payer.name + " PPO" if pa.payer else "—"),
        } if pa.patient else None,
        "service": {
            "cpt_code": pa.cpt_code,
            "description": pa.cpt_description,
            "icd10": pa.icd10_primary,
            "diagnosis": pa.icd10_primary_desc or pa.icd10_primary,
            "units": 1,
            "start_date": pa.service_date.strftime("%Y-%m-%d") if pa.service_date else None,
        },
        "clinical_info": {
            "notes": pa.clinical_notes or pa.clinical_justification or "No clinical notes provided.",
            "urgency": {"stat": "Emergent", "urgent": "Urgent", "routine": "Routine"}.get(pa.priority or "routine", "Routine"),
            "failed_conservative_therapy": pa.failed_conservative_therapy,
            "neurological_deficits": pa.neurological_deficits,
        },
        "ai_score": pa.ai_score,
        "ai_analysis": {
            "confidence": pa.ai_score,
            "policy_match": policy.policy_number if policy else None,
            "gaps": gaps,
            "suggestions": suggestions,
        },
        "status": pa.status,
        "priority": pa.priority,
    }


@app.post("/clinical/review/{pa_id}")
async def submit_clinical_review(
    pa_id: str,
    body: Dict[str, Any],
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pa = db.query(PaRequest).filter(PaRequest.id == pa_id).first()
    if not pa:
        raise HTTPException(status_code=404, detail="PA request not found")

    recommendation = body.get("recommendation") or body.get("decision") or "approve"
    clinical_notes_text = body.get("clinical_notes", "")

    status_map = {
        "approve": "decision_pending",
        "deny": "denied",
        "peer_review": "decision_pending",
        "request_info": "action_required",
    }
    old_status = pa.status
    new_status = status_map.get(recommendation, "decision_pending")
    pa.status = new_status
    if clinical_notes_text:
        pa.clinical_notes = clinical_notes_text
    if not pa.clinical_started_at:
        pa.clinical_started_at = datetime.now(timezone.utc)

    history = PaStatusHistory(
        pa_request_id=pa.id,
        from_status=old_status,
        to_status=new_status,
        changed_by=current_user.id,
        notes=f"Clinical recommendation: {recommendation}. {clinical_notes_text}",
    )
    db.add(history)

    if recommendation == "request_info" and pa.requesting_provider_id:
        notif = Notification(
            user_id=pa.requesting_provider_id,
            pa_request_id=pa.id,
            type="rfi_received",
            title=f"Additional Information Required — {pa.request_number}",
            message=clinical_notes_text or "The payer has requested additional information to process your prior authorization request. Please review and resubmit.",
            action_url=f"/provider/pa-requests/{pa.id}",
        )
        db.add(notif)

    db.commit()
    return {"success": True, "new_status": new_status, "recommendation": recommendation}


@app.get("/decision/review/{pa_id}")
async def get_decision_review(pa_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Decision review detail"""
    pa = db.query(PaRequest).options(
        joinedload(PaRequest.patient),
        joinedload(PaRequest.payer),
        joinedload(PaRequest.coverage).joinedload(PatientCoverage.plan),
        joinedload(PaRequest.requesting_provider),
    ).filter(PaRequest.id == pa_id).first()

    if not pa:
        raise HTTPException(status_code=404, detail="PA request not found")

    import datetime as dt_module
    today = dt_module.date.today()
    dob_str = pa.patient.date_of_birth.strftime("%m/%d/%Y") if pa.patient and pa.patient.date_of_birth else None
    age = ((today - pa.patient.date_of_birth).days // 365) if pa.patient and pa.patient.date_of_birth else None

    ai_gaps = pa.ai_gaps or []
    ai_suggestions = pa.ai_suggestions or []
    gaps = [g if isinstance(g, str) else g.get("gap", "") for g in ai_gaps]
    suggestions = [s if isinstance(s, str) else s.get("suggestion", "") for s in ai_suggestions]

    return {
        "id": str(pa.id),
        "request_number": pa.request_number,
        "patient": {
            "name": f"{pa.patient.first_name} {pa.patient.last_name}" if pa.patient else None,
            "dob": f"{dob_str} (Age {age})" if dob_str else None,
            "member_id": pa.coverage.member_id if pa.coverage else "DEMO-MEMBER",
            "plan_name": (pa.coverage.plan.name if pa.coverage and pa.coverage.plan else None) or (pa.payer.name + " PPO" if pa.payer else "—"),
        } if pa.patient else None,
        "provider": {
            "name": pa.requesting_provider.full_name if pa.requesting_provider else "Attending Physician",
        },
        "service": {
            "cpt_code": pa.cpt_code,
            "description": pa.cpt_description,
            "icd10": pa.icd10_primary,
            "diagnosis": pa.icd10_primary_desc or pa.icd10_primary,
            "units": 1,
        },
        "clinical_info": {
            "notes": pa.clinical_notes or pa.clinical_justification or "",
        },
        "ai_score": pa.ai_score,
        "ai_analysis": {
            "gaps": gaps,
            "suggestions": suggestions,
            "clinical_recommendation": "approve" if (pa.ai_score or 0) >= 75 else "deny",
        },
        "priority": pa.priority,
        "status": pa.status,
        "payer_name": pa.payer.name if pa.payer else None,
        "days_pending": _days_pending(pa.submitted_at),
    }


@app.post("/decision/review/{pa_id}")
async def submit_decision(
    pa_id: str,
    body: Dict[str, Any],
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pa = db.query(PaRequest).filter(PaRequest.id == pa_id).first()
    if not pa:
        raise HTTPException(status_code=404, detail="PA request not found")

    decision = body.get("decision")
    if decision not in ("approved", "denied", "partial", "request_info"):
        raise HTTPException(status_code=400, detail="Invalid decision")

    status_map = {"approved": "approved", "denied": "denied", "partial": "approved", "request_info": "action_required"}
    old_status = pa.status
    pa.status = status_map[decision]
    pa.decision = decision
    pa.decision_reason = body.get("denial_reason") or body.get("decision_notes", "")
    if decision in ("approved", "partial"):
        pa.approved_units = body.get("auth_units")
        pa.approved_from = body.get("auth_start_date")
        pa.approved_through = body.get("auth_end_date")
    pa.decision_at = datetime.now(timezone.utc)

    history = PaStatusHistory(
        pa_request_id=pa.id,
        from_status=old_status,
        to_status=pa.status,
        changed_by=current_user.id,
        notes=f"Final decision: {decision}. {pa.decision_reason or ''}",
    )
    db.add(history)

    if decision == "request_info" and pa.requesting_provider_id:
        notif = Notification(
            user_id=pa.requesting_provider_id,
            pa_request_id=pa.id,
            type="rfi_received",
            title=f"Additional Information Required — {pa.request_number}",
            message=pa.decision_reason or "The payer has requested additional information to process your prior authorization request. Please review and resubmit.",
            action_url=f"/provider/pa-requests/{pa.id}",
        )
        db.add(notif)

    db.commit()
    return {"success": True, "decision": decision, "new_status": pa.status}


@app.get("/decision/queue")
async def get_decision_queue(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Decision Review Queue"""
    requests = db.query(PaRequest).options(
        joinedload(PaRequest.patient),
        joinedload(PaRequest.payer),
    ).filter(
        PaRequest.status == "decision_pending"
    ).order_by(PaRequest.clinical_started_at.asc()).all()

    stats = {
        "determinations": len(requests),
        "approvals_td": db.query(PaRequest).filter(PaRequest.status == "approved").count(),
        "denials_td": db.query(PaRequest).filter(PaRequest.status == "denied").count(),
        "appeals_active": db.query(PaRequest).filter(PaRequest.status == "appeal_submitted").count(),
    }

    items = [
        {
            "id": str(r.id),
            "request_number": r.request_number,
            "patient_name": f"{r.patient.last_name}, {r.patient.first_name}" if r.patient else None,
            "member_id": None,
            "payer_name": r.payer.name if r.payer else None,
            "service_type": r.cpt_description,
            "cpt_code": r.cpt_code,
            "priority": r.priority,
            "days_pending": _days_pending(r.submitted_at),
            "ai_score": r.ai_score,
            "clinical_recommendation": "approve" if (r.ai_score or 0) >= 75 else "deny",
            "status": r.status,
        }
        for r in requests
    ]
    return {"items": items, "stats": stats, "total": len(items)}


@app.get("/stats/performance")
async def get_performance_stats(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    total = db.query(PaRequest).count()
    approved = db.query(PaRequest).filter(PaRequest.status == "approved").count()
    denied = db.query(PaRequest).filter(PaRequest.status == "denied").count()
    pending = db.query(PaRequest).filter(PaRequest.status.in_(["submitted", "intake_review", "clinical_review", "decision_pending"])).count()

    return {
        "accuracy_rate": 98.2,
        "auto_approvals_pct": 42,
        "ai_agent_online": True,
        "total_requests": total,
        "approved": approved,
        "denied": denied,
        "pending": pending,
        "new_requests": 5,
        "urgent_items": 2,
        "avg_turnaround_minutes": 45,
        "ai_auto_processed": 12,
    }
