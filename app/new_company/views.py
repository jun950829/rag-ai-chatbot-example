from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.new_company.helpers import find_new_company_by_external_id
from app.new_company.serializers import NewCompanyDetail


router = APIRouter(prefix="/new-companies", tags=["new-companies"])


@router.get("/external/{external_id}", response_model=NewCompanyDetail)
def get_new_company_by_external_id(external_id: str, db: Session = Depends(get_session)) -> NewCompanyDetail:
    company = find_new_company_by_external_id(db, external_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NewCompany not found")
    return NewCompanyDetail.model_validate(company)
