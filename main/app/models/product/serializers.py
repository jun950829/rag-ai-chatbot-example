from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.base import APIModel


class ProductBase(APIModel):
    external_id: str | None = None
    company_id: uuid.UUID
    image_url: str | None = None
    name_kor: str | None = None
    name_eng: str | None = None
    description_kor: str | None = None
    description_eng: str | None = None
    certification_kor: str | None = None
    certification_eng: str | None = None
    keywords_kor: str | None = None
    keywords_eng: str | None = None
    main_category_code: str | None = None
    main_category_kor: str | None = None
    main_category_eng: str | None = None
    sub_category_code: str | None = None
    sub_category_kor: str | None = None
    sub_category_eng: str | None = None
    model_name: str | None = None
    manufacturer_kor: str | None = None
    manufacturer_eng: str | None = None
    country_of_origin_code: str | None = None
    country_of_origin_kor: str | None = None
    country_of_origin_eng: str | None = None
    exhibit_year: int | None = None
    exhibition_category: str | None = None
    exhibit_hall_label_kor: str | None = None
    exhibit_hall_label_eng: str | None = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(APIModel):
    external_id: str | None = None
    company_id: uuid.UUID | None = None
    image_url: str | None = None
    name_kor: str | None = None
    name_eng: str | None = None
    description_kor: str | None = None
    description_eng: str | None = None
    certification_kor: str | None = None
    certification_eng: str | None = None
    keywords_kor: str | None = None
    keywords_eng: str | None = None
    main_category_code: str | None = None
    main_category_kor: str | None = None
    main_category_eng: str | None = None
    sub_category_code: str | None = None
    sub_category_kor: str | None = None
    sub_category_eng: str | None = None
    model_name: str | None = None
    manufacturer_kor: str | None = None
    manufacturer_eng: str | None = None
    country_of_origin_code: str | None = None
    country_of_origin_kor: str | None = None
    country_of_origin_eng: str | None = None
    exhibit_year: int | None = None
    exhibition_category: str | None = None
    exhibit_hall_label_kor: str | None = None
    exhibit_hall_label_eng: str | None = None


class ProductListItem(APIModel):
    id: uuid.UUID
    external_id: str | None = None
    company_id: uuid.UUID
    name_kor: str | None = None
    name_eng: str | None = None
    image_url: str | None = None
    model_name: str | None = None
    main_category_kor: str | None = None
    main_category_eng: str | None = None
    exhibit_year: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProductRead(ProductBase):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
