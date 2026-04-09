from __future__ import annotations

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.company.models import Company
from app.product.models import Product
from app.product.serializers import ProductCreate, ProductUpdate


def apply_product_fields(product: Product, payload: ProductCreate | ProductUpdate) -> None:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, field, value)


def find_product_by_external_id(db: Session, external_id: str | None) -> Product | None:
    if not external_id:
        return None
    return db.scalar(select(Product).where(Product.external_id == external_id))


def ensure_company_exists(db: Session, company_id) -> Company:
    company = db.get(Company, company_id)
    if company is None:
        raise ValueError("Company not found")
    return company


def apply_product_filters(
    stmt: Select[tuple[Product]],
    *,
    q: str | None = None,
    company_id=None,
) -> Select[tuple[Product]]:
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Product.name_kor.ilike(like),
                Product.name_eng.ilike(like),
                Product.external_id.ilike(like),
            )
        )
    if company_id is not None:
        stmt = stmt.where(Product.company_id == company_id)
    return stmt
