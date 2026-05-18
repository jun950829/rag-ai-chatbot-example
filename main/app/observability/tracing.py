"""파이프라인 단계용 경량 트레이싱 (표준 logging ``extra`` + 경과 ms)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, AsyncIterator

from app.core.logger import get_logger

_log = get_logger("app.observability.pipeline")


def log_stage_event(event: str, stage: str, **fields: Any) -> None:
    """구조화에 가깝게 한 줄 로그 (키=값 나열)."""

    parts = [f"event={event}", f"stage={stage}"]
    for k, v in fields.items():
        if v is None:
            continue
        parts.append(f"{k}={v!r}")
    _log.info(" ".join(parts))


@asynccontextmanager
async def trace_stage(stage: str, **fields: Any) -> AsyncIterator[None]:
    """비동기 단계 경계 — 시작/완료 + ``elapsed_ms``."""

    t0 = perf_counter()
    log_stage_event("pipeline.stage.started", stage, **fields)
    try:
        yield
    finally:
        elapsed_ms = int((perf_counter() - t0) * 1000)
        log_stage_event("pipeline.stage.completed", stage, elapsed_ms=elapsed_ms, **fields)
