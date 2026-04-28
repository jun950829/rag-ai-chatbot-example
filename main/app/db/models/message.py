"""메시지(messages) ORM 모델.

요구사항:
- UUID PK
- session_id FK
- role(user/assistant)
- content TEXT
- embedding nullable (요구사항: pgvector or float[] → float[]로 구현)
- created_at 자동 생성
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Float, Uuid

from app.db.base import Base


MessageRole = Literal["user", "assistant"]


class Message(Base):
    """대화 세션에 속한 단일 메시지(사용자/어시스턴트)."""

    __tablename__ = "messages"

    # 메시지 ID (UUID, PK)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # 세션 FK
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # 역할(user/assistant)
    role: Mapped[str] = mapped_column(Text, nullable=False)

    # 메시지 본문
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # 메시지 임베딩(옵션): float8[] 형태로 저장 (pgvector 타입 의존성 없이 운영 가능)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)

    # 생성 시각
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # 관계: 메시지 → 세션
    session: Mapped["ConversationSession"] = relationship(back_populates="messages")

    # 1:1 (메시지 → meta)
    meta: Mapped["MessageMeta"] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )

