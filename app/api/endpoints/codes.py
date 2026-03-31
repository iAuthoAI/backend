from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.db.session import get_db
from app.models.codes import CptCode, HcpcsCode, Icd10Code
from app.core.security import get_current_user

router = APIRouter()


@router.get("/cpt")
async def search_cpt(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=50),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    search = f"%{q}%"
    results = db.query(CptCode).filter(
        CptCode.is_active == True,
        (CptCode.code.ilike(search)) | (CptCode.description.ilike(search)) | (CptCode.short_description.ilike(search))
    ).limit(limit).all()

    return [
        {
            "code": c.code,
            "description": c.description,
            "short_description": c.short_description,
            "category": c.category,
            "specialty": c.specialty,
            "pa_required": c.typical_pa_required,
            "rvu": float(c.rvu) if c.rvu else None,
        }
        for c in results
    ]


@router.get("/cpt/{code}")
async def get_cpt(code: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    cpt = db.query(CptCode).filter(CptCode.code == code).first()
    if not cpt:
        return {"code": code, "description": None, "pa_required": None}
    return {
        "code": cpt.code,
        "description": cpt.description,
        "short_description": cpt.short_description,
        "category": cpt.category,
        "specialty": cpt.specialty,
        "pa_required": cpt.typical_pa_required,
        "rvu": float(cpt.rvu) if cpt.rvu else None,
    }


@router.get("/hcpcs")
async def search_hcpcs(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=50),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    search = f"%{q}%"
    results = db.query(HcpcsCode).filter(
        HcpcsCode.is_active == True,
        (HcpcsCode.code.ilike(search)) | (HcpcsCode.description.ilike(search))
    ).limit(limit).all()

    return [
        {
            "code": c.code,
            "description": c.description,
            "short_description": c.short_description,
            "category": c.category,
            "level": c.level,
            "pa_required": c.typical_pa_required,
        }
        for c in results
    ]


@router.get("/icd10")
async def search_icd10(
    q: str = Query(..., min_length=2),
    limit: int = Query(20, le=50),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    search = f"%{q}%"
    results = db.query(Icd10Code).filter(
        Icd10Code.is_active == True,
        Icd10Code.billable == True,
        (Icd10Code.code.ilike(search)) | (Icd10Code.description.ilike(search)) | (Icd10Code.short_description.ilike(search))
    ).limit(limit).all()

    return [
        {
            "code": c.code,
            "description": c.description,
            "short_description": c.short_description,
            "category": c.category,
            "billable": c.billable,
        }
        for c in results
    ]


@router.get("/icd10/{code}")
async def get_icd10(code: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    icd = db.query(Icd10Code).filter(Icd10Code.code == code).first()
    if not icd:
        return {"code": code, "description": None}
    return {
        "code": icd.code,
        "description": icd.description,
        "short_description": icd.short_description,
        "category": icd.category,
        "billable": icd.billable,
    }
