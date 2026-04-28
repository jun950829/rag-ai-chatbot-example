"""메시지 메타(message_meta) ORM 모델.

목적:
 - 추론 결과(의도, follow-up 여부, confidence)를 저장해
   재처리/분석/캐싱에 활용한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Float, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base


class MessageMeta(Base):
    """메시지 단위의 추론 메타데이터(의도/Follow-up/신뢰도)."""

    __tablename__ = "message_meta"

    # 메타 ID (UUID, PK)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # 메시지 FK (1:1)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # 의도 라벨 (예: company/product/followup/general 등)
    intent: Mapped[str] = mapped_column(Text, nullable=False)

    # follow-up 여부
    is_followup: Mapped[bool] = mapped_column(nullable=False, default=False)

    # 휴리스틱 신뢰도(0~1)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # 생성 시각
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 관계: meta → message
    message: Mapped["Message"] = relationship(back_populates="meta")

