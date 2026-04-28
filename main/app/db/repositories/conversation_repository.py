"""ConversationSession Repository.

DB 접근을 한 곳으로 모아 서비스 레이어에서 재사용한다.
모든 함수는 한글 주석을 포함한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ConversationSession


class ConversationRepository:
    """대화 세션(conversation_sessions) 전용 Repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_session(self, *, session_id: uuid.UUID | None = None, metadata: dict | None = None) -> ConversationSession:
        """세션 생성.

        - session_id를 지정하면 외부에서 생성한 UUID를 그대로 사용한다.
        - metadata는 JSONB로 저장된다.
        """

        obj = ConversationSession(
            id=session_id or uuid.uuid4(),
            metadata_json=metadata or {},
        )
        self.session.add(obj)
        await self.session.flush()  # PK 확보
        return obj

    async def get_session(self, session_id: uuid.UUID) -> ConversationSession | None:
        """세션 조회(없으면 None)."""

        stmt = select(ConversationSession).where(ConversationSession.id == session_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def update_last_message_at(self, session_id: uuid.UUID, *, last_message_at: datetime) -> None:
        """세션의 last_message_at을 갱신한다."""

        stmt = (
            update(ConversationSession)
            .where(ConversationSession.id == session_id)
            .values(last_message_at=last_message_at)
        )
        await self.session.execute(stmt)

