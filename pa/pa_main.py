from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid
import random
import string
from common.db import get_db
from pa.pa_models import PaRequest, PaStatusHistory, SupportingDocument, PaFormTemplate
from patient.patient_models import PatientCoverage
from payer.payer_models import Payer, Plan, PayerPolicy, PayerDenialReason
from codes.codes_models import CptCode, Icd10Code
from common.security import get_current_user

app = FastAPI()


def generate_request_number():
    year = datetime.now().year
    suffix = ''.join(random.choices(string.digits, k=3))
    return f"REQ-{year}-{suffix}"


class QuickReviewRequest(BaseModel):
    patient_id: str
    coverage_id: Optional[str] = None
    payer_id: Optional[str] = None
    plan_id: Optional[str] = None
    cpt_code: str
    icd10_code: str
    clinical_notes: Optional[str] = None


class CreatePARequest(BaseModel):
    patient_id: str
    coverage_id: Optional[str] = None
    payer_id: Optional[str] = None
    plan_id: Optional[str] = None
    cpt_description: Optional[str] = None
    cpt_code: str
    icd10_primary: str
    clinical_notes: Optional[str] = None
    clinical_justification: Optional[str] = None
    priority: Optional[str] = "routine"
    form_template_id: Optional[str] = None
    form_data: Optional[dict] = {}
    failed_conservative_therapy: Optional[bool] = None
    conservative_therapy_details: Optional[str] = None
    neurological_deficits: Optional[bool] = None
    neurological_details: Optional[str] = None


class SubmitPARequest(BaseModel):
    pa_request_id: str
    form_data: dict
    failed_conservative_therapy: bool
    conservative_therapy_details: Optional[str] = None
    neurological_deficits: bool
    neurological_details: Optional[str] = None
    additional_notes: Optional[str] = None


class ReviewDecision(BaseModel):
    pa_request_id: str
    action: str  # approve, deny, request_more_info, submit_to_clinical, submit_for_decision, finalize_approval
    notes: Optional[str] = None


def score_pa_request(pa_request, clinical_notes, failed_therapy, neuro_deficits, db: Session) -> dict:
    """AI scoring simulation - returns score 0-100 and analysis"""
    score = 50
    gaps = []
    suggestions = []

    # Check clinical notes quality
    if clinical_notes and len(clinical_notes) > 100:
        score += 15
    else:
        gaps.append({"gap": "Clinical notes are minimal or missing", "impact": "High Impact"})
        suggestions.append("Expand clinical notes to include specific symptoms and duration.")

    # Conservative therapy
    if failed_therapy:
        score += 20
    else:
        gaps.append({"gap": "No mention of failed conservative therapy found in notes", "impact": "High Impact"})
        suggestions.append("Document failed conservative therapy (e.g., PT, NSAIDs) > 6 weeks.")

    # Neurological deficits
    if neuro_deficits:
        score += 10
    else:
        suggestions.append("Specify any neurological deficits if present.")

    # Policy match check
    if pa_request.coverage_id:
        coverage = db.query(PatientCoverage).filter(PatientCoverage.id == str(pa_request.coverage_id)).first()
    else:
        coverage = None
    payer_id_for_policy = coverage.payer_id if coverage else pa_request.payer_id
    if payer_id_for_policy:
        all_pols = db.query(PayerPolicy).filter(
            PayerPolicy.payer_id == payer_id_for_policy,
            PayerPolicy.is_active == True
        ).all()
        if any(p.cpt_codes and pa_request.cpt_code in p.cpt_codes for p in all_pols):
            score += 5

    # Cap at 95
    score = min(score, 95)

    analysis = {
        "clinical_documentation_quality": "high" if score >= 75 else "medium" if score >= 50 else "low",
        "medical_necessity": "validated" if neuro_deficits or failed_therapy else "partial",
        "policy_match": "matched" if score >= 70 else "partial",
    }

    if not suggestions:
        suggestions.append("Documentation meets clinical guidelines. Good approval probability.")

    return {
        "score": score,
        "confidence": score,
        "analysis": analysis,
        "gaps": gaps,
        "suggestions": suggestions,
    }


def _resolve_payer_plan(request: QuickReviewRequest, db: Session):
    """Resolve payer and plan from coverage_id or payer_id/plan_id."""
    if request.coverage_id:
        coverage = db.query(PatientCoverage).options(
            joinedload(PatientCoverage.payer),
            joinedload(PatientCoverage.plan)
        ).filter(PatientCoverage.id == request.coverage_id).first()
        if coverage:
            return coverage.payer_id, coverage.payer, coverage.plan, coverage.member_id, coverage.is_active, coverage.plan.plan_type if coverage.plan else None, coverage.plan.name if coverage.plan else None

    # Fallback: resolve from payer_id/plan_id directly
    payer = db.query(Payer).filter(Payer.id == request.payer_id).first() if request.payer_id else None
    plan = db.query(Plan).filter(Plan.id == request.plan_id).first() if request.plan_id else None
    if payer:
        return str(payer.id), payer, plan, "DEMO-MEMBER", True, plan.plan_type if plan else "HMO", plan.name if plan else "Standard Plan"
    return None, None, None, None, None, None, None


@app.post("/quick-review")
async def quick_review(request: QuickReviewRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Step 1 - Quick review: check PA requirements"""
    payer_id, payer, plan, member_id, is_active, plan_type, plan_name = _resolve_payer_plan(request, db)

    if not payer:
        raise HTTPException(status_code=404, detail="Coverage or payer not found")

    cpt = db.query(CptCode).filter(CptCode.code == request.cpt_code).first()
    icd10 = db.query(Icd10Code).filter(Icd10Code.code == request.icd10_code).first()

    from sqlalchemy import cast, String
    from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
    policy = db.query(PayerPolicy).filter(
        PayerPolicy.payer_id == payer_id,
        PayerPolicy.is_active == True,
    ).all()
    policy = next((p for p in policy if p.cpt_codes and request.cpt_code in p.cpt_codes), None)

    denial_reasons = db.query(PayerDenialReason).filter(
        PayerDenialReason.payer_id == payer_id,
        PayerDenialReason.cpt_code == request.cpt_code,
        PayerDenialReason.is_active == True
    ).order_by(PayerDenialReason.frequency_percent.desc()).all()

    # Historical approval rate (simulated)
    approval_rate = 73
    avg_review_time = 9.5

    return {
        "coverage": {
            "payer_name": payer.name,
            "payer_code": payer.code,
            "plan_name": plan_name,
            "plan_type": plan_type,
            "member_id": member_id,
            "is_active": is_active,
        },
        "cpt": {
            "code": request.cpt_code,
            "description": cpt.description if cpt else "Unknown",
            "short_description": cpt.short_description if cpt else None,
            "pa_required": cpt.typical_pa_required if cpt else True,
        },
        "icd10": {
            "code": request.icd10_code,
            "description": icd10.description if icd10 else "Unknown",
            "billable": icd10.billable if icd10 else True,
        },
        "eligibility": {
            "member_eligible": True,
            "benefit_coverage_active": True,
            "network_provider_status": True,
            "pa_required": True,
        },
        "policy": {
            "policy_number": policy.policy_number if policy else None,
            "title": policy.title if policy else None,
            "requirements": policy.requirements if policy else [],
        } if policy else None,
        "denial_reasons": [
            {
                "reason_description": r.reason_description,
                "frequency_percent": float(r.frequency_percent) if r.frequency_percent else None,
                "impact_level": r.impact_level,
            }
            for r in denial_reasons
        ],
        "historical": {
            "approval_rate_90d": approval_rate,
            "avg_review_time_days": avg_review_time,
            "payer": payer.name,
        },
    }


@app.post("/ai-analysis")
async def ai_policy_analysis(request: QuickReviewRequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Step 2 - AI Policy Analysis"""
    payer_id, payer, plan, member_id, is_active, plan_type, plan_name = _resolve_payer_plan(request, db)

    if not payer:
        raise HTTPException(status_code=404, detail="Coverage or payer not found")

    # Simulated AI analysis
    score = 30 if not request.clinical_notes else 65
    gaps = []
    suggestions = []

    if not request.clinical_notes or len(request.clinical_notes) < 50:
        gaps.append({"gap": "No mention of failed conservative therapy found in notes.", "impact": "High Impact"})

    suggestions = [
        "Expand clinical notes to include specific symptoms and duration.",
        "Document failed conservative therapy (e.g., PT, NSAIDs) > 6 weeks.",
        "Specify any neurological deficits if present.",
        "Upload recent office visit notes or imaging reports.",
    ]

    all_policies = db.query(PayerPolicy).filter(
        PayerPolicy.payer_id == payer_id,
        PayerPolicy.is_active == True,
    ).all()
    policy = next((p for p in all_policies if p.cpt_codes and request.cpt_code in p.cpt_codes), None)

    denial_reasons = db.query(PayerDenialReason).filter(
        PayerDenialReason.payer_id == payer_id,
        PayerDenialReason.cpt_code == request.cpt_code,
        PayerDenialReason.is_active == True
    ).order_by(PayerDenialReason.frequency_percent.desc()).all()

    return {
        "payer": payer.name,
        "payer_code": payer.code,
        "cpt_code": request.cpt_code,
        "approval_probability": score,
        "approval_label": "Low" if score < 40 else "Medium" if score < 70 else "High",
        "gaps": gaps,
        "suggestions": suggestions,
        "relevant_policies": [
            {
                "policy_number": policy.policy_number,
                "title": policy.title,
                "description": f"Requires documentation of failed NSAID therapy > 6 weeks.",
            }
        ] if policy else [],
        "historical": {
            "approval_rate_90d": 73,
            "avg_review_time_days": 9.5,
        },
        "top_denial_reasons": [
            {
                "frequency_percent": float(r.frequency_percent) if r.frequency_percent else 0,
                "reason_description": r.reason_description,
            }
            for r in denial_reasons
        ],
        "ai_insights": {
            "clinical_documentation_quality": "high" if score >= 70 else "medium",
            "medical_necessity": "partial",
        },
    }


@app.get("/form-selection")
async def get_form_selection(
    payer_id: str,
    cpt_code: str,
    icd10_code: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Step 3 - Find the correct PA form"""
    templates = db.query(PaFormTemplate).filter(
        PaFormTemplate.payer_id == payer_id,
        PaFormTemplate.is_active == True,
    ).all()

    matched = []
    others = []

    for t in templates:
        match_score = 0
        reasons = []

        if t.cpt_codes and cpt_code in t.cpt_codes:
            match_score += 50
            reasons.append(f"Matched CPT: {cpt_code}")

        if t.form_type == "imaging":
            match_score += 30
            reasons.append("Imaging order detected")

        if icd10_code and t.cpt_codes and cpt_code in t.cpt_codes:
            match_score += 10
            reasons.append(f"Matched ICD: {icd10_code}")

        form_data = {
            "id": str(t.id),
            "form_id": t.form_id,
            "title": t.title,
            "description": t.description,
            "form_type": t.form_type,
            "version": t.version,
            "revision_date": t.revision_date.isoformat() if t.revision_date else None,
            "is_epa": t.is_epa,
            "match_score": match_score,
            "reasons": reasons,
            "field_count": len(t.fields) if t.fields else 0,
            "fields": t.fields,
        }

        if match_score >= 80:
            matched.append(form_data)
        else:
            others.append(form_data)

    matched.sort(key=lambda x: x["match_score"], reverse=True)

    return {
        "best_match": matched[0] if matched else None,
        "all_forms": matched + others,
    }


@app.post("/submit")
async def submit_pa_request(request: SubmitPARequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Submit a PA request"""
    pa = db.query(PaRequest).filter(PaRequest.id == request.pa_request_id).first()
    if not pa:
        raise HTTPException(status_code=404, detail="PA Request not found")

    # Update form data and clinical info
    pa.form_data = request.form_data
    pa.failed_conservative_therapy = request.failed_conservative_therapy
    pa.conservative_therapy_details = request.conservative_therapy_details
    pa.neurological_deficits = request.neurological_deficits
    pa.neurological_details = request.neurological_details
    if request.additional_notes:
        pa.clinical_notes = request.additional_notes

    # Run AI scoring
    ai_result = score_pa_request(
        pa,
        pa.clinical_notes,
        request.failed_conservative_therapy,
        request.neurological_deficits,
        db
    )
    pa.ai_score = ai_result["score"]
    pa.ai_confidence = ai_result["confidence"]
    pa.ai_analysis = ai_result["analysis"]
    pa.ai_gaps = ai_result["gaps"]
    pa.ai_suggestions = ai_result["suggestions"]
    pa.status = "submitted"
    pa.submission_method = "epa"
    pa.submitted_at = datetime.now(timezone.utc)

    # Add status history
    history = PaStatusHistory(
        pa_request_id=pa.id,
        from_status="draft",
        to_status="submitted",
        changed_by=current_user["user_id"],
        changed_by_role=current_user["role"],
        notes="PA request submitted via ePA",
    )
    db.add(history)
    db.commit()
    db.refresh(pa)

    return {
        "success": True,
        "request_id": str(pa.id),
        "request_number": pa.request_number,
        "submission_method": "ePA (Electronic)",
        "status": pa.status,
        "ai_score": pa.ai_score,
        "message": f"PA request {pa.request_number} submitted successfully",
    }


@app.post("/create")
async def create_pa_request(request: CreatePARequest, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Create a new PA request"""
    # Resolve coverage/payer
    resolved_coverage_id = request.coverage_id
    resolved_payer_id = request.payer_id
    resolved_plan_id = request.plan_id

    if request.coverage_id:
        coverage = db.query(PatientCoverage).filter(PatientCoverage.id == request.coverage_id).first()
        if coverage:
            resolved_payer_id = str(coverage.payer_id)
            resolved_plan_id = str(coverage.plan_id) if coverage.plan_id else None
    elif request.payer_id:
        payer = db.query(Payer).filter(Payer.id == request.payer_id).first()
        if not payer:
            raise HTTPException(status_code=404, detail="Payer not found")
    else:
        raise HTTPException(status_code=400, detail="coverage_id or payer_id required")

    cpt = db.query(CptCode).filter(CptCode.code == request.cpt_code).first()
    icd10 = db.query(Icd10Code).filter(Icd10Code.code == request.icd10_primary).first()

    request_number = generate_request_number()
    while db.query(PaRequest).filter(PaRequest.request_number == request_number).first():
        request_number = generate_request_number()

    pa = PaRequest(
        request_number=request_number,
        patient_id=request.patient_id,
        coverage_id=resolved_coverage_id,
        payer_id=resolved_payer_id,
        plan_id=resolved_plan_id,
        requesting_provider_id=current_user["user_id"],
        organization_id=current_user.get("org_id"),
        cpt_code=request.cpt_code,
        cpt_description=request.cpt_description or (cpt.description if cpt and len(cpt.description) > 6 else None) or request.cpt_code,
        icd10_primary=request.icd10_primary,
        icd10_primary_desc=icd10.description if icd10 else request.icd10_primary,
        clinical_notes=request.clinical_notes,
        clinical_justification=request.clinical_justification,
        priority=request.priority or "routine",
        status="draft",
        form_data=request.form_data or {},
    )
    db.add(pa)
    db.commit()
    db.refresh(pa)

    return {
        "id": str(pa.id),
        "request_number": pa.request_number,
        "status": pa.status,
    }


@app.get("/")
async def list_pa_requests(
    status: Optional[str] = None,
    payer_id: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = Query(20, le=100),
    offset: int = 0,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(PaRequest).options(
        joinedload(PaRequest.patient),
        joinedload(PaRequest.payer)
    )

    role = current_user.get("role")
    if role == "provider":
        query = query.filter(PaRequest.requesting_provider_id == current_user["user_id"])

    if status:
        query = query.filter(PaRequest.status == status)
    if payer_id:
        query = query.filter(PaRequest.payer_id == payer_id)
    if priority:
        query = query.filter(PaRequest.priority == priority)

    total = query.count()
    requests = query.order_by(PaRequest.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "total": total,
        "requests": [
            {
                "id": str(r.id),
                "request_number": r.request_number,
                "patient_name": f"{r.patient.first_name} {r.patient.last_name}" if r.patient else None,
                "patient_mrn": r.patient.mrn if r.patient else None,
                "cpt_code": r.cpt_code,
                "cpt_description": r.cpt_description,
                "icd10_primary": r.icd10_primary,
                "status": r.status,
                "priority": r.priority,
                "payer_name": r.payer.name if r.payer else None,
                "payer_code": r.payer.code if r.payer else None,
                "ai_score": r.ai_score,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in requests
        ]
    }


@app.get("/{pa_id}")
async def get_pa_request(pa_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    pa = db.query(PaRequest).options(
        joinedload(PaRequest.patient),
        joinedload(PaRequest.payer),
        joinedload(PaRequest.coverage).joinedload(PatientCoverage.plan),
        joinedload(PaRequest.status_history),
        joinedload(PaRequest.documents),
        joinedload(PaRequest.form_template),
    ).filter(PaRequest.id == pa_id).first()

    if not pa:
        raise HTTPException(status_code=404, detail="PA request not found")

    return {
        "id": str(pa.id),
        "request_number": pa.request_number,
        "patient": {
            "id": str(pa.patient.id),
            "mrn": pa.patient.mrn,
            "full_name": f"{pa.patient.first_name} {pa.patient.last_name}",
            "date_of_birth": pa.patient.date_of_birth.isoformat() if pa.patient.date_of_birth else None,
        } if pa.patient else None,
        "payer": {
            "name": pa.payer.name,
            "code": pa.payer.code,
        } if pa.payer else None,
        "coverage": {
            "member_id": pa.coverage.member_id,
            "plan_name": pa.coverage.plan.name if pa.coverage and pa.coverage.plan else None,
        } if pa.coverage else None,
        "cpt_code": pa.cpt_code,
        "cpt_description": pa.cpt_description,
        "icd10_primary": pa.icd10_primary,
        "icd10_primary_desc": pa.icd10_primary_desc,
        "status": pa.status,
        "priority": pa.priority,
        "clinical_notes": pa.clinical_notes,
        "clinical_justification": pa.clinical_justification,
        "failed_conservative_therapy": pa.failed_conservative_therapy,
        "conservative_therapy_details": pa.conservative_therapy_details,
        "neurological_deficits": pa.neurological_deficits,
        "neurological_details": pa.neurological_details,
        "form_data": pa.form_data,
        "ai_score": pa.ai_score,
        "ai_confidence": float(pa.ai_confidence) if pa.ai_confidence else None,
        "ai_analysis": pa.ai_analysis,
        "ai_gaps": pa.ai_gaps,
        "ai_suggestions": pa.ai_suggestions,
        "submitted_at": pa.submitted_at.isoformat() if pa.submitted_at else None,
        "created_at": pa.created_at.isoformat() if pa.created_at else None,
        "status_history": [
            {
                "from_status": h.from_status,
                "to_status": h.to_status,
                "notes": h.notes,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in pa.status_history
        ],
        "documents": [
            {
                "id": str(d.id),
                "file_name": d.file_name,
                "document_type": d.document_type,
                "storage_url": d.storage_url,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in pa.documents
        ],
        "form_template": {
            "form_id": pa.form_template.form_id,
            "title": pa.form_template.title,
            "form_type": pa.form_template.form_type,
            "fields": pa.form_template.fields,
        } if pa.form_template else None,
    }


@app.post("/review-decision")
async def review_decision(request: ReviewDecision, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    pa = db.query(PaRequest).filter(PaRequest.id == request.pa_request_id).first()
    if not pa:
        raise HTTPException(status_code=404, detail="PA Request not found")

    action_map = {
        "submit_to_clinical": ("intake_review", "clinical_review"),
        "submit_for_decision": ("clinical_review", "decision_pending"),
        "finalize_approval": ("decision_pending", "approved"),
        "reject": (None, "denied"),
        "request_more_info": (None, "action_required"),
    }

    if request.action not in action_map:
        raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")

    _, new_status = action_map[request.action]
    old_status = pa.status

    history = PaStatusHistory(
        pa_request_id=pa.id,
        from_status=old_status,
        to_status=new_status,
        changed_by=current_user["user_id"],
        changed_by_role=current_user["role"],
        notes=request.notes,
    )

    pa.status = new_status
    if new_status == "approved":
        pa.decision = "APPROVED"
        pa.decision_at = datetime.now(timezone.utc)
    elif new_status == "denied":
        pa.decision = "DENIED"
        pa.decision_reason = request.notes
        pa.decision_at = datetime.now(timezone.utc)

    db.add(history)
    db.commit()

    return {"success": True, "new_status": new_status, "request_number": pa.request_number}


@app.post("/{pa_id}/resubmit")
async def resubmit_pa(
    pa_id: str,
    body: dict,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Provider resubmits a PA after payer requested more info."""
    pa = db.query(PaRequest).filter(
        PaRequest.id == pa_id,
        PaRequest.requesting_provider_id == current_user["user_id"],
    ).first()
    if not pa:
        raise HTTPException(status_code=404, detail="PA request not found")
    if pa.status != "action_required":
        raise HTTPException(status_code=400, detail="PA is not in action_required status")

    additional_notes = body.get("additional_notes", "")
    if additional_notes:
        pa.clinical_notes = (pa.clinical_notes or "") + f"\n\n[Provider Response]: {additional_notes}"

    old_status = pa.status
    pa.status = "submitted"
    pa.submitted_at = datetime.now(timezone.utc)

    history = PaStatusHistory(
        pa_request_id=pa.id,
        from_status=old_status,
        to_status="submitted",
        changed_by=current_user["user_id"],
        notes=f"Provider resubmitted with additional info: {additional_notes}" if additional_notes else "Provider resubmitted",
    )
    db.add(history)
    db.commit()
    return {"success": True, "new_status": "submitted"}
