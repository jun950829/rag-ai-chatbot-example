from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from typing import Any, Optional

try:
    from redis.asyncio import Redis  # type: ignore
except Exception:  # pragma: no cover
    Redis = None  # type: ignore

from app.core.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_ANSWER_TTL = 3600              # 1 h
_RETRIEVAL_CARDS_TTL = 21600    # 6 h
_CARD_DETAIL_TTL = 86400        # 24 h


def _answer_key(q: str) -> str:
    return f"chat:answer:{hashlib.sha256((q or '').encode()).hexdigest()}"


def _retrieval_cards_key(q: str) -> str:
    return f"chat:retrieval_cards:{hashlib.sha256((q or '').encode()).hexdigest()}"


def _card_detail_key(entity_kind: str, external_id: str, language: str) -> str:
    return f"chat:card_detail:{entity_kind}:{external_id}:{language}"


async def _redis() -> Optional["Redis"]:
    st = get_settings()
    if not st.redis_url or Redis is None:
        return None
    return Redis.from_url(st.redis_url, encoding="utf-8", decode_responses=True)


# ── answer cache ──────────────────────────────────────────────────

async def get_cached_answer(query: str) -> str | None:
    r = await _redis()
    if r is None:
        return None
    try:
        return await r.get(_answer_key(query))
    except Exception as e:
        logger.warning("redis answer cache get failed: %s", e)
        return None
    finally:
        with suppress(Exception):
            await r.close()


async def save_cached_answer(query: str, answer: str) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        await r.set(_answer_key(query), answer, ex=_ANSWER_TTL)
    except Exception as e:
        logger.warning("redis answer cache set failed: %s", e)
    finally:
        with suppress(Exception):
            await r.close()


# ── retrieval + cards cache ───────────────────────────────────────

async def get_retrieval_cards_cache(query: str) -> dict[str, Any] | None:
    r = await _redis()
    if r is None:
        return None
    try:
        raw = await r.get(_retrieval_cards_key(query))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning("redis retrieval_cards cache get failed: %s", e)
        return None
    finally:
        with suppress(Exception):
            await r.close()


async def save_retrieval_cards_cache(
    query: str,
    *,
    intent: str,
    cards: list[dict[str, Any]],
    context: str,
    short_answer: str,
    language: str,
) -> None:
    r = await _redis()
    if r is None:
        return
    payload = json.dumps(
        {"intent": intent, "cards": cards, "context": context,
         "short_answer": short_answer, "language": language},
        ensure_ascii=False,
    )
    try:
        await r.set(_retrieval_cards_key(query), payload, ex=_RETRIEVAL_CARDS_TTL)
    except Exception as e:
        logger.warning("redis retrieval_cards cache set failed: %s", e)
    finally:
        with suppress(Exception):
            await r.close()


# ── card detail cache ─────────────────────────────────────────────

async def get_card_detail_cache(
    entity_kind: str, external_id: str, language: str,
) -> str | None:
    r = await _redis()
    if r is None:
        return None
    try:
        return await r.get(_card_detail_key(entity_kind, external_id, language))
    except Exception as e:
        logger.warning("redis card_detail cache get failed: %s", e)
        return None
    finally:
        with suppress(Exception):
            await r.close()


async def save_card_detail_cache(
    entity_kind: str, external_id: str, language: str, answer: str,
) -> None:
    r = await _redis()
    if r is None:
        return
    try:
        await r.set(
            _card_detail_key(entity_kind, external_id, language),
            answer,
            ex=_CARD_DETAIL_TTL,
        )
    except Exception as e:
        logger.warning("redis card_detail cache set failed: %s", e)
    finally:
        with suppress(Exception):
            await r.close()
