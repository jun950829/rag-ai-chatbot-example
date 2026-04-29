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
        """session_id 문자열을 UUID로 정규화하고, 없으면 세션을 생성한다.

        운영에서는 브라우저/클라이언트가 UUID가 아닌 임의 문자열을 쓰는 경우가 흔하다.
        이때도 DB PK(UUID)로 저장할 수 있도록 **결정적(deterministic) 매핑**을 사용한다.
        - UUID 문자열이면 그대로 사용
        - 그 외 문자열이면 uuid5로 안정적으로 변환
        """

        raw = (session_id or "").strip()
        try:
            sid = uuid.UUID(raw)
        except Exception:
            # 같은 session_id 문자열은 항상 같은 UUID로 매핑된다.
            sid = uuid.uuid5(uuid.NAMESPACE_URL, raw or "anonymous")
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

