from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NewCompany(Base):
    __tablename__ = "new_company"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Source CSV row identifier (we also use this as the external_id for upserts)
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

