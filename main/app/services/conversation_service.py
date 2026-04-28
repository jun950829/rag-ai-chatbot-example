"""ConversationService.

역할:
- 세션 생성/조회
- DB 메시지 → ConversationMemory hydrate
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import ConversationRepository, MessageRepository
from app.rag.retrieval.memory import ConversationMemory


class ConversationService:
    """대화 세션 단위의 비즈니스 로직 서비스."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversations = ConversationRepository(db)
        self.messages = MessageRepository(db)

    async def get_or_create_session(self, session_id: str) -> uuid.UUID:
        """session_id 문자열을 UUID로 정규화하고, 없으면 세션을 생성한다."""

        sid = uuid.UUID(session_id)
        existing = await self.conversations.get_session(sid)
        if existing is None:
            await self.conversations.create_session(session_id=sid)
            await self.db.commit()
        return sid

    async def hydrate_memory(self, session_id: uuid.UUID, *, limit: int = 5) -> ConversationMemory:
        """DB에 저장된 최근 메시지를 ConversationMemory로 로드한다."""

        mem = ConversationMemory(max_turns=max(3, int(limit)))
        rows = await self.messages.get_last_messages(session_id, limit=limit)
        for m in rows:
            mem.add(str(m.role), str(m.content))
        return mem

