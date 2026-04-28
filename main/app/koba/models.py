from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class KobaExhibitor(Base):
    """KOBA exhibitor row (from KOBA_ExhibitorsExport CSV)."""

    __tablename__ = "koba_exhibitor"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)

    company_name_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name_eng: Mapped[str | None] = mapped_column(Text, nullable=True)

    exhibit_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    exhibition_category_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    booth_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    homepage: Mapped[str | None] = mapped_column(String(512), nullable=True)

    country_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    country_label_kor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_label_eng: Mapped[str | None] = mapped_column(String(100), nullable=True)

    exhibit_hall_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exhibit_hall_label_kor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exhibit_hall_label_eng: Mapped[str | None] = mapped_column(String(100), nullable=True)

    exhibit_status_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exhibit_status_label_kor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exhibit_status_label_eng: Mapped[str | None] = mapped_column(String(100), nullable=True)

    badge_list: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    badge_label_kor_list: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    badge_label_eng_list: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    item_main_category_label_kor_list: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    item_main_category_label_eng_list: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    item_sub_category_label_kor_list: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    item_sub_category_label_eng_list: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    company_address_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_address_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    exhibition_manager_tel: Mapped[str | None] = mapped_column(String(50), nullable=True)

    company_description_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_description_eng: Mapped[str | None] = mapped_column(Text, nullable=True)

    drawing_info_company_name_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    drawing_info_company_name_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    drawing_info_company_x_coordinate_kor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drawing_info_company_x_coordinate_eng: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drawing_info_company_y_coordinate_kor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drawing_info_company_y_coordinate_eng: Mapped[int | None] = mapped_column(Integer, nullable=True)

    company_logo_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class KobaExhibitItem(Base):
    """KOBA exhibit item / product row (from KOBA_ExhibitItemsExport CSV)."""

    __tablename__ = "koba_exhibit_item"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(512), unique=True, nullable=True, index=True)

    product_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    exhibitor_sn: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    item_main_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_main_category_label_kor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_main_category_label_eng: Mapped[str | None] = mapped_column(String(255), nullable=True)

    item_sub_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_sub_category_label_kor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    item_sub_category_label_eng: Mapped[str | None] = mapped_column(String(255), nullable=True)

    product_name_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_name_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_keywords_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_keywords_eng: Mapped[str | None] = mapped_column(Text, nullable=True)

    country_of_origin: Mapped[str | None] = mapped_column(String(32), nullable=True)
    country_of_origin_label_kor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    country_of_origin_label_eng: Mapped[str | None] = mapped_column(String(128), nullable=True)

    model_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    manufacturer_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    manufacturer_eng: Mapped[str | None] = mapped_column(Text, nullable=True)

    product_description_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_description_eng: Mapped[str | None] = mapped_column(Text, nullable=True)

    certification_status_kor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    certification_status_eng: Mapped[str | None] = mapped_column(String(255), nullable=True)

    company_name_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    exhibit_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exhibition_category_label: Mapped[str | None] = mapped_column(String(100), nullable=True)

    exhibit_hall: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exhibit_hall_label_kor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exhibit_hall_label_eng: Mapped[str | None] = mapped_column(String(255), nullable=True)

    exhibit_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exhibit_status_label_kor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exhibit_status_label_eng: Mapped[str | None] = mapped_column(String(255), nullable=True)

    product_image_link: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
