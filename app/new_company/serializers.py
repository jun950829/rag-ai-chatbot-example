from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.base import APIModel


class NewCompanyBase(APIModel):
    external_id: str | None = None

    company_name_kor: str | None = None
    company_name_eng: str | None = None

    exhibit_year: int | None = None
    exhibition_category_label: str | None = None
    booth_number: str | None = None

    homepage: str | None = None

    country_code: str | None = None
    country_label_kor: str | None = None
    country_label_eng: str | None = None

    exhibit_hall_code: str | None = None
    exhibit_hall_label_kor: str | None = None
    exhibit_hall_label_eng: str | None = None

    exhibit_status_code: str | None = None
    exhibit_status_label_kor: str | None = None
    exhibit_status_label_eng: str | None = None

    badge_list: list[int] = Field(default_factory=list)
    badge_label_kor_list: list[str] = Field(default_factory=list)
    badge_label_eng_list: list[str] = Field(default_factory=list)

    item_main_category_label_kor_list: list[str] = Field(default_factory=list)
    item_main_category_label_eng_list: list[str] = Field(default_factory=list)
    item_sub_category_label_kor_list: list[str] = Field(default_factory=list)
    item_sub_category_label_eng_list: list[str] = Field(default_factory=list)

    company_address_kor: str | None = None
    company_address_eng: str | None = None
    exhibition_manager_tel: str | None = None

    company_description_kor: str | None = None
    company_description_eng: str | None = None

    drawing_info_company_name_kor: str | None = None
    drawing_info_company_name_eng: str | None = None
    drawing_info_company_x_coordinate_kor: int | None = None
    drawing_info_company_x_coordinate_eng: int | None = None
    drawing_info_company_y_coordinate_kor: int | None = None
    drawing_info_company_y_coordinate_eng: int | None = None

    company_logo_link: str | None = None


class NewCompanyCreate(NewCompanyBase):
    pass


class NewCompanyUpdate(APIModel):
    external_id: str | None = None

    company_name_kor: str | None = None
    company_name_eng: str | None = None

    exhibit_year: int | None = None
    exhibition_category_label: str | None = None
    booth_number: str | None = None

    homepage: str | None = None

    country_code: str | None = None
    country_label_kor: str | None = None
    country_label_eng: str | None = None

    exhibit_hall_code: str | None = None
    exhibit_hall_label_kor: str | None = None
    exhibit_hall_label_eng: str | None = None

    exhibit_status_code: str | None = None
    exhibit_status_label_kor: str | None = None
    exhibit_status_label_eng: str | None = None

    badge_list: list[int] | None = None
    badge_label_kor_list: list[str] | None = None
    badge_label_eng_list: list[str] | None = None

    item_main_category_label_kor_list: list[str] | None = None
    item_main_category_label_eng_list: list[str] | None = None
    item_sub_category_label_kor_list: list[str] | None = None
    item_sub_category_label_eng_list: list[str] | None = None

    company_address_kor: str | None = None
    company_address_eng: str | None = None
    exhibition_manager_tel: str | None = None

    company_description_kor: str | None = None
    company_description_eng: str | None = None

    drawing_info_company_name_kor: str | None = None
    drawing_info_company_name_eng: str | None = None
    drawing_info_company_x_coordinate_kor: int | None = None
    drawing_info_company_x_coordinate_eng: int | None = None
    drawing_info_company_y_coordinate_kor: int | None = None
    drawing_info_company_y_coordinate_eng: int | None = None

    company_logo_link: str | None = None


class NewCompanyListItem(APIModel):
    id: uuid.UUID
    external_id: str | None = None
    company_name_kor: str | None = None
    company_name_eng: str | None = None
    booth_number: str | None = None
    exhibit_year: int | None = None
    exhibition_category_label: str | None = None
    country_code: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NewCompanyDetail(NewCompanyBase):
    id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None

