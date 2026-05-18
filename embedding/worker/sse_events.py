"""SSE 이벤트 이름 — ``main/app/streaming/sse_events.py`` 와 동일 계약 유지."""

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


def stream_payload_json(event: str, data: Any) -> str:
    return json.dumps({"event": event, "data": data}, ensure_ascii=False)
