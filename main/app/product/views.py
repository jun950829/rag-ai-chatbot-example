from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.product.helpers import (
    apply_product_fields,
    apply_product_filters,
    ensure_company_exists,
    find_product_by_external_id,
)
from app.product.models import Product
from app.product.serializers import ProductCreate, ProductListItem, ProductRead, ProductUpdate


router = APIRouter(prefix="/products", tags=["products"])


@router.get("/", response_model=list[ProductListItem])
def list_products(
    q: str | None = Query(default=None),
    company_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_session),
) -> list[ProductListItem]:
    stmt = select(Product).order_by(Product.created_at.desc(), Product.id).offset(offset).limit(limit)
    stmt = apply_product_filters(stmt, q=q, company_id=company_id)
    rows = db.scalars(stmt).all()
    return [ProductListItem.model_validate(row) for row in rows]


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: uuid.UUID, db: Session = Depends(get_session)) -> ProductRead:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return ProductRead.model_validate(product)


@router.post("/", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_session)) -> ProductRead:
    existing = find_product_by_external_id(db, payload.external_id)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product external_id already exists")

    try:
        ensure_company_exists(db, payload.company_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found") from exc

    product = Product()
    apply_product_fields(product, payload)
    db.add(product)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Failed to create product") from exc

    db.refresh(product)
    return ProductRead.model_validate(product)


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    db: Session = Depends(get_session),
) -> ProductRead:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    if payload.external_id and payload.external_id != product.external_id:
        existing = find_product_by_external_id(db, payload.external_id)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Product external_id already exists")

    if payload.company_id is not None:
        try:
            ensure_company_exists(db, payload.company_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found") from exc

    apply_product_fields(product, payload)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Failed to update product") from exc

    db.refresh(product)
    return ProductRead.model_validate(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: uuid.UUID, db: Session = Depends(get_session)) -> Response:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    db.delete(product)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
