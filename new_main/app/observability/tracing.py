"""파이프라인 단계 트레이싱 (경량)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from typing import Any, AsyncIterator

from app.core.logger import get_logger

logger = get_logger("pipeline")


def log_event(event: str, **fields: Any) -> None:
    parts = [f"event={event}"]
    for k, v in fields.items():
        if v is None:
            continue
        parts.append(f"{k}={v!r}")
    logger.info(" ".join(parts))


@asynccontextmanager
async def trace_stage(stage: str, **fields: Any) -> AsyncIterator[None]:
    t0 = perf_counter()
    log_event("stage.started", stage=stage, **fields)
    try:
        yield
    finally:
        log_event("stage.completed", stage=stage, elapsed_ms=int((perf_counter() - t0) * 1000), **fields)

