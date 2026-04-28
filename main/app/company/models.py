from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.product.models import Product


class Company(Base):
    __tablename__ = "company"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    logo_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    name_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_eng: Mapped[str | None] = mapped_column(Text, nullable=True)
    desc_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    desc_eng: Mapped[str | None] = mapped_column(Text, nullable=True)

    homepage: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tel: Mapped[str | None] = mapped_column(String(50), nullable=True)

    exhibit_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    exhibition_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    booth_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    exhibit_hall_label_kor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    exhibit_hall_label_eng: Mapped[str | None] = mapped_column(String(100), nullable=True)

    country_code: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    country_label_kor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country_label_eng: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_kor: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_eng: Mapped[str | None] = mapped_column(Text, nullable=True)

    item_main_categories_kor: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    item_main_categories_eng: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    item_sub_categories_kor: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    item_sub_categories_eng: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    products: Mapped[list["Product"]] = relationship(
        "Product",
        back_populates="company",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
