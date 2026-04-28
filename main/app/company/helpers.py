from __future__ import annotations

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.company.models import Company
from app.company.serializers import CompanyCreate, CompanyUpdate


def apply_company_fields(company: Company, payload: CompanyCreate | CompanyUpdate) -> None:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field, value)


def find_company_by_external_id(db: Session, external_id: str | None) -> Company | None:
    if not external_id:
        return None
    return db.scalar(select(Company).where(Company.external_id == external_id))


def apply_company_filters(
    stmt: Select[tuple[Company]],
    *,
    q: str | None = None,
    exhibit_year: int | None = None,
) -> Select[tuple[Company]]:
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Company.name_kor.ilike(like),
                Company.name_eng.ilike(like),
                Company.external_id.ilike(like),
            )
        )
    if exhibit_year is not None:
        stmt = stmt.where(Company.exhibit_year == exhibit_year)
    return stmt
