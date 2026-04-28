from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.company.helpers import apply_company_fields, apply_company_filters, find_company_by_external_id
from app.company.models import Company
from app.company.serializers import CompanyCreate, CompanyDetail, CompanyListItem, CompanyUpdate
from app.db import get_session


router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/", response_model=list[CompanyListItem])
def list_companies(
    q: str | None = Query(default=None),
    exhibit_year: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[CompanyListItem]:
    stmt = select(Company).order_by(Company.created_at.desc(), Company.id).offset(offset).limit(limit)
    stmt = apply_company_filters(stmt, q=q, exhibit_year=exhibit_year)
    rows = db.scalars(stmt).all()
    return [CompanyListItem.model_validate(row) for row in rows]


@router.get("/{company_id}", response_model=CompanyDetail)
def get_company(company_id: uuid.UUID, db: Session = Depends(get_session)) -> CompanyDetail:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return CompanyDetail.model_validate(company)


@router.post("/", response_model=CompanyDetail, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_session)) -> CompanyDetail:
    existing = find_company_by_external_id(db, payload.external_id)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Company external_id already exists")

    company = Company()
    apply_company_fields(company, payload)
    db.add(company)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Failed to create company") from exc

    db.refresh(company)
    return CompanyDetail.model_validate(company)


@router.patch("/{company_id}", response_model=CompanyDetail)
def update_company(
    company_id: uuid.UUID,
    payload: CompanyUpdate,
    db: Session = Depends(get_session),
) -> CompanyDetail:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    if payload.external_id and payload.external_id != company.external_id:
        existing = find_company_by_external_id(db, payload.external_id)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Company external_id already exists")

    apply_company_fields(company, payload)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Failed to update company") from exc

    db.refresh(company)
    return CompanyDetail.model_validate(company)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_company(company_id: uuid.UUID, db: Session = Depends(get_session)) -> Response:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    db.delete(company)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
