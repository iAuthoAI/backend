from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.payer import Payer, Plan, PayerPolicy
from app.core.security import get_current_user

router = APIRouter()


@router.get("/")
async def list_payers(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    payers = db.query(Payer).filter(Payer.is_active == True).order_by(Payer.name).all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "code": p.code,
            "type": p.type,
            "inquiry_phone": p.inquiry_phone,
            "epa_supported": p.epa_supported,
        }
        for p in payers
    ]


@router.get("/plans")
async def list_all_plans(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    plans = db.query(Plan).join(Payer).filter(Payer.is_active == True).order_by(Payer.name, Plan.name).all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "plan_type": p.plan_type,
            "payer_id": str(p.payer_id),
            "payer_name": p.payer.name,
            "payer_code": p.payer.code,
        }
        for p in plans
    ]


@router.get("/{payer_id}/plans")
async def list_payer_plans(payer_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    plans = db.query(Plan).filter(Plan.payer_id == payer_id).order_by(Plan.name).all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "plan_type": p.plan_type,
            "payer_id": str(p.payer_id),
        }
        for p in plans
    ]


@router.get("/{payer_id}/policies")
async def get_payer_policies(payer_id: str, cpt_code: str = None, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(PayerPolicy).filter(PayerPolicy.payer_id == payer_id, PayerPolicy.is_active == True)
    if cpt_code:
        query = query.filter(PayerPolicy.cpt_codes.contains([cpt_code]))

    policies = query.all()
    return [
        {
            "id": str(p.id),
            "policy_number": p.policy_number,
            "title": p.title,
            "service_category": p.service_category,
            "cpt_codes": p.cpt_codes,
            "requirements": p.requirements,
            "medical_necessity_criteria": p.medical_necessity_criteria,
            "prior_auth_required": p.prior_auth_required,
            "step_therapy_required": p.step_therapy_required,
        }
        for p in policies
    ]
