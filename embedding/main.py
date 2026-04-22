from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib import request as urllib_request

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
)
from embedding.retrieval import RetrievalConfig, execute_retrieval_pipeline

templates = Jinja2Templates(directory=str(_BASE / "templates"))
app = FastAPI(title="Local Embedding Tool", version="0.1.0")
logger = logging.getLogger(__name__)

JOB_LOCK = threading.Lock()
JOB_STORE: dict[str, dict[str, Any]] = {}


def _job_set(job_id: str, **fields: Any) -> None:
    with JOB_LOCK:
        rec = JOB_STORE.setdefault(job_id, {})
        rec.update(fields)


def _format_search_context(results: list[dict[str, Any]], *, limit: int = 5) -> str:
    lines: list[str] = []
    for i, r in enumerate(results[:limit], start=1):
        score = r.get("score")
        score_txt = f"{float(score):.4f}" if isinstance(score, (int, float)) else "-"
        content = (r.get("content") or "").strip().replace("\n", " / ")
        if len(content) > 220:
            content = content[:220].rstrip() + "..."
        lines.append(
            f"[{i}] score={score_txt}, lang={r.get('lang')}, type={r.get('chunk_typ')}, "
            f"external_id={r.get('external_id')}, source_field={r.get('source_field')}, content={content}"
        )
    return "\n".join(lines)


def _generate_korean_answer_with_ollama(
    *,
    query: str,
    results: list[dict[str, Any]],
    model: str,
    base_url: str,
    timeout_sec: int = 90,
) -> str:
    if not results:
        return "검색 결과가 없어 답변을 생성할 수 없습니다."

    context_text = _format_search_context(results, limit=6)
    payload = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "system",
                "content": (
                    "너는 전시 참가업체 검색 도우미다. 반드시 한국어로 답한다. "
                    "주어진 검색 결과만 근거로 요약하고, 모르면 모른다고 답한다. "
                    "답변은 3~5문장으로 간결하게 작성한다."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"질문: {query}\n\n"
                    f"검색 결과:\n{context_text}\n\n"
                    "요청: 질문에 가장 적합한 업체를 한국어로 추천하고, 근거를 함께 설명해줘."
                ),
            },
        ],
    }

    endpoint = base_url.rstrip("/") + "/api/chat"
    req = urllib_request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=timeout_sec) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    return ((data.get("message") or {}).get("content") or "").strip() or "LLM이 빈 답변을 반환했습니다."


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
            upsert_counts = _upsert_embeddings(results, model_id=model_id, progress=progress)
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

    upsert_counts = _upsert_embeddings(results, model_id=model_id)
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
    answer_mode: str = Form(default="template"),
    llm_model: str = Form(default=os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")),
    llm_base_url: str = Form(default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")),
) -> JSONResponse:
    if not (query or "").strip():
        raise HTTPException(status_code=400, detail="검색어가 비어 있습니다.")
    if lang not in {"all", "kor", "eng"}:
        raise HTTPException(status_code=400, detail="lang must be one of: all, kor, eng")
    if chunk_type not in {"all", "profile", "evidence"}:
        raise HTTPException(status_code=400, detail="chunk_type must be one of: all, profile, evidence")
    if answer_mode not in {"template", "ollama"}:
        raise HTTPException(status_code=400, detail="answer_mode must be one of: template, ollama")

    try:
        retrieval_payload = execute_retrieval_pipeline(
            query,
            config=RetrievalConfig(
                model_id=model_id,
                device=device or None,
                top_k_per_query=max(6, top_k),
                final_top_k=max(1, top_k),
                score_cutoff=0.22,
                evidence_ratio=0.6,
                min_queries=3,
                max_queries=5,
                rrf_k=60,
                context_limit=6,
            ),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"임베딩 모델 로드 실패: {e}") from e

    results = retrieval_payload["final_results"]
    response_mode = retrieval_payload.get("response_mode", "retrieval")
    logger.info(
        "[retrieval] done mode=%s intent=%s language=%s queries=%d results=%d",
        response_mode,
        retrieval_payload["intent"],
        retrieval_payload["language"],
        len(retrieval_payload["planned_queries"]),
        len(results),
    )

    if response_mode == "intent_heuristic":
        answer_korean = retrieval_payload.get("heuristic_answer") or "요청 의도에 맞춘 안내 응답입니다."
        answer_meta: dict[str, Any] = {"mode": "intent_heuristic"}
    else:
        answer_korean = build_korean_search_answer(query, results)
        answer_meta = {"mode": "template"}

    if response_mode == "retrieval" and answer_mode == "ollama":
        try:
            answer_korean = _generate_korean_answer_with_ollama(
                query=query,
                results=results,
                model=llm_model,
                base_url=llm_base_url,
            )
            answer_meta = {"mode": "ollama", "model": llm_model, "base_url": llm_base_url}
        except Exception as e:
            answer_korean = (
                f"[LLM 호출 실패로 템플릿 응답으로 대체] {build_korean_search_answer(query, results)} "
                f"(원인: {e})"
            )
            answer_meta = {"mode": "template_fallback", "error": str(e), "requested_mode": "ollama"}

    return JSONResponse(
        {
            "query": query,
            "top_k": max(1, int(top_k)),
            "lang": lang,
            "chunk_type": chunk_type,
            "count": len(results),
            "retrieval": {
                "intent": retrieval_payload["intent"],
                "language": retrieval_payload["language"],
                "planned_queries": retrieval_payload["planned_queries"],
                "llm_context": retrieval_payload["llm_context"],
                "rrf_candidates": len(retrieval_payload["fused_results"]),
                "step_logs": retrieval_payload.get("step_logs", []),
                "response_mode": response_mode,
            },
            "answer_korean": answer_korean,
            "answer_meta": answer_meta,
            "results": results,
        }
    )
