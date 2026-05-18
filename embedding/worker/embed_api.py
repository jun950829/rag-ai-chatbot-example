"""Embedding HTTP API (no Redis queue).

new_main이 기대하는 계약:
- POST /v1/embed/query   (form: query, model_id, device) -> {"embedding":[...], "embedding_dim":..., "model_id":...}
- POST /v1/embed/queries (form: queries(JSON list str), model_id, device) -> {"embeddings":[[...]], "count":..., ...}
"""

from __future__ import annotations

import json
import os

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse

from worker.embedding import build_embeddings_batch

app = FastAPI(title="Embedding API", version="0.1.0", docs_url="/docs", redoc_url="/redoc")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "embedding-api"}


@app.post("/v1/embed/query")
def embed_query_endpoint(
    query: str = Form(...),
    model_id: str = Form(default=os.environ.get("EMBEDDING_MODEL_ID", "Qwen/Qwen3-Embedding-0.6B")),
    device: str = Form(default=os.environ.get("EMBEDDING_DEVICE", "cpu")),
) -> JSONResponse:
    _ = (device or "").strip()  # reserved (실제 모델 도입 시 사용)
    q = (query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query is empty")
    vec = build_embeddings_batch([q])[0]
    return JSONResponse({"embedding": vec, "embedding_dim": len(vec), "model_id": model_id})


@app.post("/v1/embed/queries")
def embed_queries_endpoint(
    queries: str = Form(..., description='JSON 배열 문자열, 예: ["q1","q2"]'),
    model_id: str = Form(default=os.environ.get("EMBEDDING_MODEL_ID", "Qwen/Qwen3-Embedding-0.6B")),
    device: str = Form(default=os.environ.get("EMBEDDING_DEVICE", "cpu")),
) -> JSONResponse:
    _ = (device or "").strip()
    try:
        parsed = json.loads(queries)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"queries JSON 파싱 실패: {e}") from e
    if not isinstance(parsed, list):
        raise HTTPException(status_code=400, detail="queries는 JSON 배열이어야 합니다.")
    if not parsed:
        raise HTTPException(status_code=400, detail="queries가 비어 있습니다.")
    if len(parsed) > 32:
        raise HTTPException(status_code=400, detail="queries는 최대 32개까지 허용됩니다.")
    cleaned: list[str] = []
    for x in parsed:
        s = str(x).strip()
        if not s:
            raise HTTPException(status_code=400, detail="queries 항목에 빈 문자열이 있습니다.")
        cleaned.append(s)
    vecs = build_embeddings_batch(cleaned)
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

