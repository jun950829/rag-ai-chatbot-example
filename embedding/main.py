from __future__ import annotations

import asyncio
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

_BASE = Path(__file__).resolve().parent
_ROOT = _BASE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from embedding.pipeline import (
    DEFAULT_EMBEDDING_DEVICE,
    DEFAULT_EMBEDDING_MODEL_ID,
    _build_embeddings,
    _fetch_new_company_rows,
    _upsert_embeddings,
    build_korean_search_answer,
    embed_query_text,
    search_embedding_tables,
)

templates = Jinja2Templates(directory=str(_BASE / "templates"))
app = FastAPI(title="Local Embedding Tool", version="0.1.0")

JOB_LOCK = threading.Lock()
JOB_STORE: dict[str, dict[str, Any]] = {}


def _job_set(job_id: str, **fields: Any) -> None:
    with JOB_LOCK:
        rec = JOB_STORE.setdefault(job_id, {})
        rec.update(fields)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


async def _run_embed_job_async(
    job_id: str,
    rows: list[dict[str, str]],
    model_id: str,
    batch_size: int,
    entity_batch_size: int,
    device: Optional[str],
    evidence_max_chars: int,
    evidence_overlap: int,
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
                progress=progress,
            )
            progress("DB 적재(upsert) 시작", 95)
            upsert_counts = _upsert_embeddings(results, progress=progress)
            return {
                "rows_in_new_company": len(rows),
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
) -> JSONResponse:
    rows = _fetch_new_company_rows(limit)
    if not rows:
        raise HTTPException(status_code=400, detail="new_company 테이블에 데이터가 없습니다.")

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
) -> JSONResponse:
    rows = _fetch_new_company_rows(limit)
    if not rows:
        raise HTTPException(status_code=400, detail="new_company 테이블에 데이터가 없습니다.")

    try:
        results = _build_embeddings(
            rows,
            model_id=model_id,
            batch_size=batch_size,
            entity_batch_size=entity_batch_size,
            device=device or None,
            max_chars=evidence_max_chars,
            overlap=evidence_overlap,
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

    upsert_counts = _upsert_embeddings(results)
    return JSONResponse(
        {
            "status": "done",
            "rows_in_new_company": len(rows),
            "upsert_counts": upsert_counts,
            "total_upserted": sum(upsert_counts.values()),
        }
    )


@app.post("/search")
async def search_embeddings(
    query: str = Form(...),
    model_id: str = Form(default=os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID)),
    device: str = Form(default=DEFAULT_EMBEDDING_DEVICE),
    top_k: int = Form(default=10),
    lang: str = Form(default="all"),
    chunk_type: str = Form(default="all"),
) -> JSONResponse:
    if not (query or "").strip():
        raise HTTPException(status_code=400, detail="검색어가 비어 있습니다.")
    if lang not in {"all", "kor", "eng"}:
        raise HTTPException(status_code=400, detail="lang must be one of: all, kor, eng")
    if chunk_type not in {"all", "profile", "evidence"}:
        raise HTTPException(status_code=400, detail="chunk_type must be one of: all, profile, evidence")

    try:
        qvec = embed_query_text(query, model_id=model_id, device=device or None)
        results = search_embedding_tables(
            query_embedding=qvec,
            top_k=top_k,
            lang=lang,
            chunk_type=chunk_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"임베딩 모델 로드 실패: {e}") from e

    return JSONResponse(
        {
            "query": query,
            "top_k": max(1, int(top_k)),
            "lang": lang,
            "chunk_type": chunk_type,
            "count": len(results),
            "answer_korean": build_korean_search_answer(query, results),
            "results": results,
        }
    )
