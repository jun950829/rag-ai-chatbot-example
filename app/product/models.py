from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.company.models import Company


class Product(Base):
    __tablename__ = "product"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("company.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    name_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    description_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    certification_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    certification_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_category_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    main_category_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    main_category_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    sub_category_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sub_category_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    sub_category_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    manufacturer_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    manufacturer_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_of_origin_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    country_of_origin_kor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_of_origin_eng: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exhibit_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    exhibition_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exhibit_hall_label_kor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exhibit_hall_label_eng: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    company: Mapped["Company"] = relationship("Company", back_populates="products")
