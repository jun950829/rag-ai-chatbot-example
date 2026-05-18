"""큐 챗봇 Redis 스트림 → SSE 이벤트 이름과 JSON 직렬화.

워커(``embedding/worker``)는 별도 이미지이므로 상수는
``embedding/worker/sse_events.py`` 와 동일하게 유지한다.
"""

from __future__ import annotations

import json
from typing import Any

EVENT_STAGE = "stage"
EVENT_RETRIEVAL = "retrieval"
EVENT_CITATION = "citation"
EVENT_DELTA = "delta"
EVENT_FINAL = "final"
EVENT_ERROR = "error"
EVENT_DONE = "done"
EVENT_RECOMMENDATION = "recommendation"

# 하위 호환(레거시 클라이언트)
EVENT_TOKEN_LEGACY = "token"
EVENT_CARDS_LEGACY = "cards"
EVENT_FOLLOWUPS_LEGACY = "followups"


def stream_payload_json(event: str, data: Any) -> str:
    """Redis RPUSH 에 넣는 한 줄 JSON (``{"event":..., "data":...}``)."""

    return json.dumps({"event": event, "data": data}, ensure_ascii=False)
