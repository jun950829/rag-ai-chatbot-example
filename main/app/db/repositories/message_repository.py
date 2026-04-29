"""Message/MessageMeta Repository.

요구사항:
- save_message()
- get_recent_messages(limit=5)
- get_last_messages(limit=5)
모든 함수에 한글 주석 작성
"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, MessageMeta


class MessageRepository:
    """메시지(messages) + 메타(message_meta) Repository."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_message(
        self,
        *,
        session_id: uuid.UUID,
        role: str,
        content: str,
        embedding: list[float] | None = None,
        intent: str | None = None,
        is_followup: bool | None = None,
        confidence: float | None = None,
        retrieval_topic: str | None = None,
    ) -> Message:
        """메시지를 저장하고, 필요 시 메타도 함께 저장한다."""

        msg = Message(
            session_id=session_id,
            role=role,
            content=content,
            embedding=embedding,
        )
        self.session.add(msg)
        await self.session.flush()

        if intent is not None and is_followup is not None and confidence is not None:
            # --- 단계: 사용자 메타에 검색 축(retrieval_topic)을 함께 기록한다 ---
            rt = (retrieval_topic or "all").strip().lower()
            if rt not in {"company", "product", "all"}:
                rt = "all"
            meta = MessageMeta(
                message_id=msg.id,
                intent=intent,
                retrieval_topic=rt,
                is_followup=bool(is_followup),
                confidence=float(confidence),
            )
            self.session.add(meta)
            await self.session.flush()
        return msg

    async def get_recent_messages(self, session_id: uuid.UUID, *, limit: int = 5) -> list[Message]:
        """최근 메시지 N개(최신순)를 조회한다."""

        stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(desc(Message.created_at))
            .limit(max(1, int(limit)))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_last_messages(self, session_id: uuid.UUID, *, limit: int = 5) -> list[Message]:
        """최근 메시지 N개를 시간순(오래된→최신)으로 반환한다."""

        rows = await self.get_recent_messages(session_id, limit=limit)
        return list(reversed(rows))

