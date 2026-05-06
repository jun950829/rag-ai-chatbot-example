"""채팅 세션·메시지 접근 동기(SQLAlchemy Engine) 구현.

`run_vector_search` 는 FastAPI/asyncio 컨텍스트에서 실행되며 AsyncSession 과
임베딩 검색용 동기 엔진이 같은 프로세스에 공존할 때 MissingGreenlet 이 날 수 있다.
브라우저 ``session_id`` 로 히스토리를 불러오고 검색 결과를 저장하는 경로만
순수 동기 커넥션으로 처리한다(OpenAI 호출은 그대로 async).
"""

from __future__ import annotations

import uuid
from typing import Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.rag.retrieval.memory import ConversationMemory


def resolve_browser_session_uuid(session_id: str) -> uuid.UUID:
    """ConversationService 와 동일 규칙: UUID 문자열이면 그대로, 아니면 uuid5 URL 네임스페이스."""
    raw = (session_id or "").strip()
    try:
        return uuid.UUID(raw)
    except Exception:
        return uuid.uuid5(uuid.NAMESPACE_URL, raw or "anonymous")


def sync_load_memory_for_session(*, engine: Engine, browser_session_id: str, limit: int) -> Tuple[ConversationMemory, uuid.UUID]:
    """세션 행 보장 후 최근 메시지를 ConversationMemory 로 적재한다."""
    sid = resolve_browser_session_uuid(browser_session_id)
    lim = max(1, int(limit))
    mem = ConversationMemory(max_turns=max(3, lim))

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO conversation_sessions (id, metadata)
                VALUES (:id, CAST(:meta AS jsonb))
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": sid, "meta": "{}"},
        )
        res = conn.execute(
            text(
                """
                SELECT role, content FROM messages
                WHERE session_id = :sid
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"sid": sid, "lim": lim},
        )
        rows = list(res.mappings().all())

    for row in reversed(rows):
        mem.add(str(row["role"]), str(row["content"]))
    return mem, sid


def sync_save_user_message(
    *,
    engine: Engine,
    session_pk: uuid.UUID,
    content: str,
    intent: str,
    is_followup: bool,
    confidence: float,
    retrieval_topic: str,
) -> None:
    msg_id = uuid.uuid4()
    meta_id = uuid.uuid4()
    rt = (retrieval_topic or "all").strip().lower()
    if rt not in {"company", "product", "all"}:
        rt = "all"

    with engine.begin() as conn:
        created_at = conn.execute(
            text(
                """
                INSERT INTO messages (id, session_id, role, content, embedding)
                VALUES (:id, :sid, 'user', :content, NULL)
                RETURNING created_at
                """
            ),
            {"id": msg_id, "sid": session_pk, "content": content},
        ).scalar_one()
        conn.execute(
            text(
                """
                INSERT INTO message_meta (id, message_id, intent, retrieval_topic, is_followup, confidence)
                VALUES (:id, :mid, :intent, :rt, :isf, :conf)
                """
            ),
            {
                "id": meta_id,
                "mid": msg_id,
                "intent": intent,
                "rt": rt,
                "isf": bool(is_followup),
                "conf": float(confidence),
            },
        )
        conn.execute(
            text(
                """
                UPDATE conversation_sessions
                   SET last_message_at = :ts, updated_at = now()
                 WHERE id = :sid
                """
            ),
            {"ts": created_at, "sid": session_pk},
        )


def sync_save_assistant_message(*, engine: Engine, session_pk: uuid.UUID, content: str) -> None:
    msg_id = uuid.uuid4()
    with engine.begin() as conn:
        created_at = conn.execute(
            text(
                """
                INSERT INTO messages (id, session_id, role, content, embedding)
                VALUES (:id, :sid, 'assistant', :content, NULL)
                RETURNING created_at
                """
            ),
            {"id": msg_id, "sid": session_pk, "content": content},
        ).scalar_one()
        conn.execute(
            text(
                """
                UPDATE conversation_sessions
                   SET last_message_at = :ts, updated_at = now()
                 WHERE id = :sid
                """
            ),
            {"ts": created_at, "sid": session_pk},
        )
