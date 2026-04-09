from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.new_company.models import NewCompany
from app.new_company.serializers import NewCompanyCreate, NewCompanyUpdate


def apply_new_company_fields(company: NewCompany, payload: NewCompanyCreate | NewCompanyUpdate) -> None:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field, value)


def find_new_company_by_external_id(db: Session, external_id: str | None) -> NewCompany | None:
    if not external_id:
        return None
    return db.scalar(select(NewCompany).where(NewCompany.external_id == external_id))

