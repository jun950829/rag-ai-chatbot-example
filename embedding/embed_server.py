"""Local embedding inference API only (no search UI, no vector DB search in this process)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse

_BASE = Path(__file__).resolve().parent
_ROOT = _BASE.parent
_MAIN_ROOT = _ROOT / "main"
# 루트 app 제거 후에도 `from app...` 임포트가 main/app를 가리키도록 우선순위를 고정한다.
if str(_MAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_MAIN_ROOT))
if str(_ROOT) not in sys.path:
    sys.path.insert(1, str(_ROOT))

from app.rag.pipeline import (
    DEFAULT_EMBEDDING_DEVICE,
    DEFAULT_EMBEDDING_MODEL_ID,
    _build_embeddings,
    _embed_texts,
    _fetch_koba_exhibit_item_rows,
    _fetch_koba_exhibitor_rows,
    _upsert_embeddings,
    embed_query_text,
)

app = FastAPI(title="Local Embedding API", version="0.3.0", docs_url="/docs", redoc_url="/redoc")

JOB_LOCK = threading.Lock()
JOB_STORE: dict[str, dict[str, Any]] = {}


def _job_set(job_id: str, **fields: Any) -> None:
    with JOB_LOCK:
        rec = JOB_STORE.setdefault(job_id, {})
        rec.update(fields)


@app.get("/", include_in_schema=False)
def root() -> dict[str, Any]:
    return {
        "service": "embedding-api",
        "docs": "/docs",
        "endpoints": {
            "health": "GET /health",
            "embed_query": "POST /v1/embed/query",
            "embed_queries": "POST /v1/embed/queries",
            "embed_sync": "POST /embed",
            "embed_job": "POST /embed/job",
            "embed_job_status": "GET /embed/job/{job_id}/status",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "embedding-api"}


@app.post("/v1/embed/query")
def embed_query_endpoint(
    query: str = Form(...),
    model_id: str = Form(default=os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID)),
    device: str = Form(default=DEFAULT_EMBEDDING_DEVICE),
) -> JSONResponse:
    if not (query or "").strip():
        raise HTTPException(status_code=400, detail="query is empty")
    try:
        vec = embed_query_text(query, model_id=model_id, device=device or None, remote_base_url=None)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"임베딩 모델 로드 실패: {e}") from e
    return JSONResponse({"embedding": vec, "embedding_dim": len(vec), "model_id": model_id})


@app.post("/v1/embed/queries")
def embed_queries_endpoint(
    queries: str = Form(..., description="JSON 배열 문자열, 예: [\"q1\",\"q2\"]"),
    model_id: str = Form(default=os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID)),
    device: str = Form(default=DEFAULT_EMBEDDING_DEVICE),
) -> JSONResponse:
    try:
        parsed = json.loads(queries)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"queries JSON 파싱 실패: {e}") from e
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="queries는 JSON 배열이어야 합니다.")
    if not parsed:
        raise HTTPException(status_code=400, detail="queries가 비어 있습니다.")
    if len(parsed) > 16:
        raise HTTPException(status_code=400, detail="queries는 최대 16개까지 허용됩니다.")
    cleaned: list[str] = []
    for x in parsed:
        s = str(x).strip()
        if not s:
            raise HTTPException(status_code=400, detail="queries 항목에 빈 문자열이 있습니다.")
        cleaned.append(s)
    try:
        vecs = _embed_texts(cleaned, model_id=model_id, device=device or None, batch_size=min(32, len(cleaned)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"임베딩 모델 로드 실패: {e}") from e
    if len(vecs) != len(cleaned):
        raise HTTPException(status_code=500, detail="배치 임베딩 결과 개수가 입력과 일치하지 않습니다.")
    return JSONResponse(
        {
            "embeddings": vecs,
            "count": len(vecs),
            "embedding_dim": len(vecs[0]) if vecs else 0,
            "model_id": model_id,
        }
    )


def _resolve_target_rows(
    target: str,
    limit: Optional[int],
) -> tuple[str, list[dict[str, str]]]:
    t = (target or "kprint_exhibitors").strip().lower()
    if t in ("exhibitor", "exhibitors", "kprint_exhibitors"):
        return "exhibitor", _fetch_koba_exhibitor_rows(limit)
    if t in ("exhibit_item", "exhibit_items", "items", "kprint_exhibit_items"):
        return "exhibit_item", _fetch_koba_exhibit_item_rows(limit)
    raise ValueError(f"unknown target={target!r} (use kprint_exhibitors|kprint_exhibit_items)")


async def _run_embed_job_async(
    job_id: str,
    rows: list[dict[str, str]],
    model_id: str,
    batch_size: int,
    entity_batch_size: int,
    device: Optional[str],
    evidence_max_chars: int,
    evidence_overlap: int,
    entity: str,
) -> None:
    def work() -> Optional[dict[str, Any]]:
        def progress(message: str, percent: int) -> None:
            _job_set(job_id, status="running", message=message, percent=min(99, percent))

        try:
            progress("임베딩 파이프라인 시작", 4)
            results = _build_embeddings(
                rows,
                model_id=model_id,
                batch_size=batch_size,
                entity_batch_size=entity_batch_size,
                device=device,
                max_chars=evidence_max_chars,
                overlap=evidence_overlap,
                koba_entity=entity,  # type: ignore[arg-type]
                progress=progress,
            )
            progress("DB 적재(upsert) 시작", 95)
            upsert_counts = _upsert_embeddings(
                results,
                model_id=model_id,
                koba_entity=entity,  # type: ignore[arg-type]
                progress=progress,
            )
            return {
                "entity": entity,
                "rows_embedded": len(rows),
                "upsert_counts": upsert_counts,
                "total_upserted": sum(upsert_counts.values()),
            }
        except ImportError as e:
            _job_set(
                job_id,
                status="error",
                message="필요 패키지가 없습니다 (Qwen3-VL 경로)",
                percent=0,
                error_detail=str(e),
            )
            return None
        except Exception as e:
            _job_set(job_id, status="error", message=str(e), percent=0, error_detail=str(e))
            return None

    summary = await asyncio.to_thread(work)
    if summary is not None:
        _job_set(
            job_id,
            status="done",
            message="임베딩 및 DB 적재가 완료되었습니다.",
            percent=100,
            result=summary,
        )


@app.post("/embed/job")
async def start_embed_job(
    background_tasks: BackgroundTasks,
    model_id: str = Form(default=os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID)),
    batch_size: int = Form(default=8),
    entity_batch_size: int = Form(default=64),
    device: str = Form(default=DEFAULT_EMBEDDING_DEVICE),
    evidence_max_chars: int = Form(default=1200),
    evidence_overlap: int = Form(default=150),
    limit: Optional[int] = Form(default=None),
    target: str = Form(default="kprint_exhibitors"),
) -> JSONResponse:
    try:
        entity, rows = _resolve_target_rows(target, limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not rows:
        raise HTTPException(
            status_code=400,
            detail=f"KPRINT 소스 '{target}' 테이블에 임베딩할 행이 없습니다. 먼저 ingest 스크립트로 CSV를 적재하세요.",
        )

    job_id = str(uuid.uuid4())
    _job_set(job_id, status="queued", message="작업이 대기열에 등록되었습니다.", percent=0)
    background_tasks.add_task(
        _run_embed_job_async,
        job_id,
        rows,
        model_id,
        batch_size,
        entity_batch_size,
        device or None,
        evidence_max_chars,
        evidence_overlap,
        entity,
    )
    return JSONResponse({"job_id": job_id})


@app.get("/embed/job/{job_id}/status")
def embed_job_status(job_id: str) -> JSONResponse:
    with JOB_LOCK:
        job = JOB_STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return JSONResponse(job)


@app.post("/embed")
async def embed_sync(
    model_id: str = Form(default=os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID)),
    batch_size: int = Form(default=8),
    entity_batch_size: int = Form(default=64),
    device: str = Form(default=DEFAULT_EMBEDDING_DEVICE),
    evidence_max_chars: int = Form(default=1200),
    evidence_overlap: int = Form(default=150),
    limit: Optional[int] = Form(default=None),
    target: str = Form(default="kprint_exhibitors"),
) -> JSONResponse:
    try:
        entity, rows = _resolve_target_rows(target, limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not rows:
        raise HTTPException(
            status_code=400,
            detail=f"KPRINT 소스 '{target}' 테이블에 임베딩할 행이 없습니다.",
        )

    try:
        results = _build_embeddings(
            rows,
            model_id=model_id,
            batch_size=batch_size,
            entity_batch_size=entity_batch_size,
            device=device or None,
            max_chars=evidence_max_chars,
            overlap=evidence_overlap,
            koba_entity=entity,  # type: ignore[arg-type]
        )
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=(
                "Qwen3-VL-Embedding 모델에 필요한 패키지가 없습니다. "
                "예: pip install 'transformers>=4.57' 'qwen-vl-utils>=0.0.14'. "
                f"원인: {e}"
            ),
        ) from e

    upsert_counts = _upsert_embeddings(
        results,
        model_id=model_id,
        koba_entity=entity,  # type: ignore[arg-type]
    )
    return JSONResponse(
        {
            "status": "done",
            "entity": entity,
            "rows_embedded": len(rows),
            "upsert_counts": upsert_counts,
            "total_upserted": sum(upsert_counts.values()),
        }
    )
