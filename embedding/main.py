from __future__ import annotations

import io
import json
import os
import sys
import uuid
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import sqlalchemy as sa


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="Local Embedding Tool", version="0.1.0")

from app.db import engine  # noqa: E402


PROFILE_BASE_COLUMNS: tuple[str, ...] = (
    "homepage",
    "exhibit_year",
    "exhibition_category_label",
    "booth_number",
    "country_code",
    "exhibit_hall_code",
)
PROFILE_KOR_COLUMNS: tuple[str, ...] = ("company_name_kor", "country_label_kor", "exhibit_hall_label_kor")
PROFILE_ENG_COLUMNS: tuple[str, ...] = ("company_name_eng", "country_label_eng", "exhibit_hall_label_eng")


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_kor_col(name: str) -> bool:
    return "_kor" in name


def _is_eng_col(name: str) -> bool:
    return "_eng" in name


def _chunk_text(text: str, *, max_chars: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


@lru_cache(maxsize=2)
def _get_model(model_id: str, device: str | None):
    from sentence_transformers import SentenceTransformer

    kwargs: dict[str, Any] = {"trust_remote_code": True}
    if device:
        kwargs["device"] = device
    return SentenceTransformer(model_id, **kwargs)


def _to_jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)


def _encode(embedder, texts: list[str], *, batch_size: int) -> list[list[float]]:
    vectors = embedder.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [v.astype("float32").tolist() for v in vectors]


def _profile_text(row: dict[str, str], *, lang: str) -> str:
    cols = list(PROFILE_BASE_COLUMNS)
    if lang == "kor":
        cols.extend(PROFILE_KOR_COLUMNS)
    else:
        cols.extend(PROFILE_ENG_COLUMNS)
    lines = [f"{c}: {_safe_str(row.get(c))}" for c in cols if _safe_str(row.get(c))]
    return "\n".join(lines).strip()


def _evidence_chunks(
    row: dict[str, str],
    *,
    lang: str,
    max_chars: int,
    overlap: int,
) -> list[dict[str, Any]]:
    skip = set(PROFILE_BASE_COLUMNS) | set(PROFILE_KOR_COLUMNS) | set(PROFILE_ENG_COLUMNS)
    chunks: list[dict[str, Any]] = []
    for col, raw in row.items():
        if col in skip:
            continue
        value = _safe_str(raw)
        if not value:
            continue

        # language split:
        # - kor table: kor + neutral columns
        # - eng table: eng + neutral columns
        if lang == "kor" and _is_eng_col(col):
            continue
        if lang == "eng" and _is_kor_col(col):
            continue

        base = f"{col}: {value}"
        for idx, piece in enumerate(_chunk_text(base, max_chars=max_chars, overlap=overlap)):
            chunks.append({"source_field": col, "chunk_index": idx, "content": piece})
    return chunks


def _build_embeddings(
    rows: list[dict[str, str]],
    *,
    model_id: str,
    batch_size: int,
    device: str | None,
    max_chars: int,
    overlap: int,
) -> dict[str, list[dict[str, Any]]]:
    embedder = _get_model(model_id, device)
    outputs: dict[str, list[dict[str, Any]]] = {
        "new_company_profile_embedding_tbd_kor": [],
        "new_company_profile_embedding_tbd_eng": [],
        "new_company_evidence_embedding_tbd_kor": [],
        "new_company_evidence_embedding_tbd_eng": [],
    }

    profile_jobs: list[tuple[str, dict[str, Any], str]] = []
    evidence_jobs: list[tuple[str, dict[str, Any], str]] = []

    for i, row in enumerate(rows):
        new_company_id = row.get("id") or row.get("external_id") or f"row-{i+1}"
        external_id = row.get("external_id") or ""

        for lang in ("kor", "eng"):
            ptxt = _profile_text(row, lang=lang)
            if ptxt:
                profile_jobs.append(
                    (
                        f"new_company_profile_embedding_tbd_{lang}",
                        {
                            "id": str(uuid.uuid4()),
                            "new_company_id": new_company_id,
                            "external_id": external_id,
                            "lang": lang,
                            "content": ptxt,
                            "model": model_id,
                        },
                        ptxt,
                    )
                )

            for ev in _evidence_chunks(row, lang=lang, max_chars=max_chars, overlap=overlap):
                evidence_jobs.append(
                    (
                        f"new_company_evidence_embedding_tbd_{lang}",
                        {
                            "id": str(uuid.uuid4()),
                            "new_company_id": new_company_id,
                            "external_id": external_id,
                            "lang": lang,
                            "source_field": ev["source_field"],
                            "chunk_index": ev["chunk_index"],
                            "content": ev["content"],
                            "model": model_id,
                        },
                        ev["content"],
                    )
                )

    if profile_jobs:
        vectors = _encode(embedder, [t for _, _, t in profile_jobs], batch_size=batch_size)
        for (table, rec, _), vec in zip(profile_jobs, vectors, strict=True):
            rec["embedding_dim"] = len(vec)
            rec["embedding"] = vec
            outputs[table].append(rec)

    if evidence_jobs:
        vectors = _encode(embedder, [t for _, _, t in evidence_jobs], batch_size=batch_size)
        for (table, rec, _), vec in zip(evidence_jobs, vectors, strict=True):
            rec["embedding_dim"] = len(vec)
            rec["embedding"] = vec
            outputs[table].append(rec)

    return outputs


def _fetch_new_company_rows(limit: int | None) -> list[dict[str, str]]:
    metadata = sa.MetaData()
    new_company = sa.Table("new_company", metadata, autoload_with=engine)

    stmt = sa.select(new_company)
    if "created_at" in new_company.c:
        stmt = stmt.order_by(new_company.c.created_at.asc())
    if limit is not None:
        stmt = stmt.limit(limit)

    rows: list[dict[str, str]] = []
    with engine.connect() as conn:
        result = conn.execute(stmt).mappings().all()
        for record in result:
            row: dict[str, str] = {}
            for col in new_company.columns:
                value = record.get(col.name)
                if isinstance(value, list):
                    row[col.name] = ", ".join(str(v) for v in value)
                else:
                    row[col.name] = "" if value is None else str(value)
            rows.append(row)
    return rows


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/embed")
async def embed_csv(
    model_id: str = Form(default=os.environ.get("EMBEDDING_MODEL_ID", "Qwen/Qwen3-VL-Embedding-2B")),
    batch_size: int = Form(default=8),
    device: str = Form(default="cpu"),
    evidence_max_chars: int = Form(default=1200),
    evidence_overlap: int = Form(default=150),
    limit: Optional[int] = Form(default=None),
) -> StreamingResponse:
    rows = _fetch_new_company_rows(limit)
    if not rows:
        raise HTTPException(status_code=400, detail="new_company 테이블에 데이터가 없습니다.")

    results = _build_embeddings(
        rows,
        model_id=model_id,
        batch_size=batch_size,
        device=device or None,
        max_chars=evidence_max_chars,
        overlap=evidence_overlap,
    )

    out = io.BytesIO()
    with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for table_name, records in results.items():
            zf.writestr(f"{table_name}.jsonl", _to_jsonl(records))
        summary = {
            "model_id": model_id,
            "rows_in_new_company": len(rows),
            "counts": {k: len(v) for k, v in results.items()},
        }
        zf.writestr("summary.json", json.dumps(summary, ensure_ascii=False, indent=2))

    out.seek(0)
    return StreamingResponse(
        out,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=new_company_embeddings_split.zip"},
    )

