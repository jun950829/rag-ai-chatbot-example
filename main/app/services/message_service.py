"""MessageService.

역할:
- 메시지 저장
- follow-up 판단을 위한 데이터 제공/계산
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import ConversationRepository, MessageRepository


_PRONOUNS = ("그거", "그것", "그 회사", "그 업체", "it", "that", "this")
_CONTINUATION_PREFIX = ("그럼", "그리고", "또", "추가로", "then", "also", "what about")


def _tokenize(text: str) -> set[str]:
    """간단 토크나이저: 한글/영문/숫자 토큰만 추출."""

    t = (text or "").lower()
    toks = re.findall(r"[가-힣a-z0-9]{2,}", t)
    return set(toks)


def is_followup_v2(
    *,
    current: str,
    history: Sequence[str],
    min_overlap: int = 1,
) -> tuple[bool, float, dict]:
    """LLM 없이 follow-up 여부를 휴리스틱으로 판단한다.

    요구사항 포함:
    1) 최근 메시지 3~5개 조회(호출자가 history로 전달)
    2) 조건:
      - 짧은 질문 + history
      - 대명사 포함
      - 이전 메시지 키워드 포함 여부(교집합)
      - continuation prefix
    3) keyword overlap 구현
    """

    q = (current or "").strip()
    if not q:
        return False, 0.0, {"reason": "empty"}

    hist = [h for h in (history or []) if (h or "").strip()]
    has_history = len(hist) > 0
    q_norm = q.lower().strip()

    # (A) 짧은 질문 + history
    if has_history and len(q_norm) <= 15:
        return True, 0.75, {"reason": "short_with_history"}

    # (B) 대명사 포함
    if any(p.lower() in q_norm for p in _PRONOUNS):
        return True, 0.8, {"reason": "pronoun"}

    # (C) continuation prefix
    if any(q_norm.startswith(p.lower()) for p in _CONTINUATION_PREFIX):
        return True, 0.7, {"reason": "continuation_prefix"}

    # (D) keyword overlap
    q_tokens = _tokenize(q_norm)
    if has_history and q_tokens:
        best = 0
        best_hit = None
        for h in hist[-5:]:
            ht = _tokenize(h)
            ov = len(q_tokens & ht)
            if ov > best:
                best = ov
                best_hit = h
        if best >= min_overlap:
            # overlap이 클수록 신뢰도 증가
            conf = min(0.95, 0.55 + 0.15 * float(best))
            return True, conf, {"reason": "keyword_overlap", "overlap": best, "hit": (best_hit or "")[:120]}

    return False, 0.2 if has_history else 0.05, {"reason": "no_signal"}


class MessageService:
    """메시지 저장/분석 서비스."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversations = ConversationRepository(db)
        self.messages = MessageRepository(db)

    async def save_user_message(
        self,
        *,
        session_id: uuid.UUID,
        content: str,
        intent: str,
        is_followup: bool,
        confidence: float,
        retrieval_topic: str | None = None,
    ) -> None:
        """사용자 메시지를 DB에 저장하고 세션 last_message_at 갱신."""

        # --- 단계: 파이프라인에서 산출한 검색 축(retrieval_topic)을 message_meta에 함께 저장한다 ---
        msg = await self.messages.save_message(
            session_id=session_id,
            role="user",
            content=content,
            intent=intent,
            is_followup=is_followup,
            confidence=confidence,
            retrieval_topic=retrieval_topic,
        )
        await self.conversations.update_last_message_at(session_id, last_message_at=msg.created_at)
        await self.db.commit()

    async def save_assistant_message(self, *, session_id: uuid.UUID, content: str) -> None:
        """어시스턴트 메시지를 DB에 저장한다."""

        msg = await self.messages.save_message(session_id=session_id, role="assistant", content=content)
        await self.conversations.update_last_message_at(session_id, last_message_at=msg.created_at)
        await self.db.commit()

