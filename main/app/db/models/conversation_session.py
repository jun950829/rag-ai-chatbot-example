"""대화 세션(conversation_sessions) ORM 모델.

요구사항:
- UUID PK
- created_at/updated_at 자동 생성
- last_message_at, summary, metadata(JSONB)
- 모든 필드/클래스에 한글 주석
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base


class ConversationSession(Base):
    """대화 세션 단위(사용자 세션/컨텍스트)의 최상위 엔티티."""

    __tablename__ = "conversation_sessions"

    # 세션 ID (UUID, PK)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # 생성 시각 (서버 타임)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # 수정 시각 (서버 타임)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    # 마지막 메시지 시각(성능 최적화를 위한 denormalized 필드)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 요약(옵션: 장기 운영에서 세션 요약 저장)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 자유 메타데이터(클라이언트/디바이스/AB테스트 등)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    # 1:N 관계 (세션 → 메시지)
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",  # N+1 방지
    )

