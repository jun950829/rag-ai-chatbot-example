"""Redis 키 빌더. embedding 캐시·retrieval 캐시·rate limit 은 설정 추가 시 여기 확장."""

from __future__ import annotations

import hashlib


def chat_answer_cache_key(*, prefix: str, message: str) -> str:
    digest = hashlib.sha256(message.strip().encode("utf-8")).hexdigest()
    return f"{prefix}{digest}"


def llm_stream_key(*, stream_prefix: str, request_id: str) -> str:
    return f"{stream_prefix}{request_id}"


def llm_trace_key(*, trace_prefix: str, request_id: str) -> str:
    return f"{trace_prefix}{request_id}"
