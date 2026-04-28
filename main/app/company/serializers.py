from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.base import APIModel


class CompanyBase(APIModel):
    external_id: str | None = None
    logo_url: str | None = None
    name_kor: str | None = None
    name_eng: str | None = None
    desc_kor: str | None = None
    desc_eng: str | None = None
    homepage: str | None = None
    tel: str | None = None
    exhibit_year: int | None = None
    exhibition_category: str | None = None
    booth_number: str | None = None
    exhibit_hall_label_kor: str | None = None
    exhibit_hall_label_eng: str | None = None
    country_code: str | None = None
    country_label_kor: str | None = None
    country_label_eng: str | None = None
    address_kor: str | None = None
    address_eng: str | None = None
    item_main_categories_kor: list[str] = Field(default_factory=list)
    item_main_categories_eng: list[str] = Field(default_factory=list)
    item_sub_categories_kor: list[str] = Field(default_factory=list)
    item_sub_categories_eng: list[str] = Field(default_factory=list)


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(APIModel):
    external_id: str | None = None
    logo_url: str | None = None
    name_kor: str | None = None
    name_eng: str | None = None
    desc_kor: str | None = None
    desc_eng: str | None = None
    homepage: str | None = None
    tel: str | None = None
    exhibit_year: int | None = None
    exhibition_category: str | None = None
    booth_number: str | None = None
    exhibit_hall_label_kor: str | None = None
    exhibit_hall_label_eng: str | None = None
    country_code: str | None = None
    country_label_kor: str | None = None
    country_label_eng: str | None = None
    address_kor: str | None = None
    address_eng: str | None = None
    item_main_categories_kor: list[str] | None = None
    item_main_categories_eng: list[str] | None = None
    item_sub_categories_kor: list[str] | None = None
    item_sub_categories_eng: list[str] | None = None


class CompanyListItem(APIModel):
    id: uuid.UUID
    external_id: str | None = None
    name_kor: str | None = None
    name_eng: str | None = None
    logo_url: str | None = None
    homepage: str | None = None
    booth_number: str | None = None
    exhibit_year: int | None = None
    exhibition_category: str | None = None
    country_code: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CompanyDetail(CompanyBase):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None
