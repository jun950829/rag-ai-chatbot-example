"""DB fetch → embed → upsert into four pgvector tables (no FastAPI)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from urllib import request as urllib_request
from urllib.parse import urlencode
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

import sqlalchemy as sa
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/rag/pipeline.py -> repo root is two levels above this file
RAG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RAG_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_EMBEDDING_MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_EMBEDDING_DEVICE = os.environ.get("EMBEDDING_DEVICE", "mps")


@dataclass(frozen=True)
class ModelTableSet:
    profile_kor: str
    profile_eng: str
    evidence_kor: str
    evidence_eng: str


QWEN_TABLE_SET = ModelTableSet(
    profile_kor="new_company_profile_embedding_qwen3_0_6b_kor",
    profile_eng="new_company_profile_embedding_qwen3_0_6b_eng",
    evidence_kor="new_company_evidence_embedding_qwen3_0_6b_kor",
    evidence_eng="new_company_evidence_embedding_qwen3_0_6b_eng",
)
BGE_M3_TABLE_SET = ModelTableSet(
    profile_kor="new_company_profile_embedding_bge_m3_kor",
    profile_eng="new_company_profile_embedding_bge_m3_eng",
    evidence_kor="new_company_evidence_embedding_bge_m3_kor",
    evidence_eng="new_company_evidence_embedding_bge_m3_eng",
)

# Backward-compatible aliases for older imports/scripts.
PROFILE_TABLE_KOR = QWEN_TABLE_SET.profile_kor
PROFILE_TABLE_ENG = QWEN_TABLE_SET.profile_eng
EVIDENCE_TABLE_KOR = QWEN_TABLE_SET.evidence_kor
EVIDENCE_TABLE_ENG = QWEN_TABLE_SET.evidence_eng

_UPSERT_ROWS_PER_EXECUTE = 1000


def _resolve_device(device: str | None) -> str | None:
    requested = (device or "").strip().lower() or DEFAULT_EMBEDDING_DEVICE
    if requested != "mps":
        return requested
    try:
        import torch

        if torch.backends.mps.is_available() and torch.backends.mps.is_built():
            return "mps"
    except Exception:
        pass
    return "cpu"


class _EmbeddingLocalSettings(BaseSettings):
    embedding_database_url: Optional[str] = None
    database_url: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(RAG_DIR / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def _resolve_database_url() -> str:
    settings = _EmbeddingLocalSettings()
    url = settings.embedding_database_url or settings.database_url
    in_container = (PROJECT_ROOT / ".dockerenv").exists() or Path("/.dockerenv").exists()
    if not url:
        if in_container:
            return "postgresql+psycopg://postgres:postgres@db:5432/rag_template"
        return "postgresql+psycopg://postgres:postgres@localhost:5432/rag_template"

    if "@db:" in url and not in_container:
        return url.replace("@db:", "@localhost:")
    if "@localhost:" in url and in_container:
        return url.replace("@localhost:", "@db:")
    return url


engine = sa.create_engine(_resolve_database_url(), future=True, pool_pre_ping=True)

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


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"


def _is_qwen3_vl_embedding_model(model_id: str) -> bool:
    m = model_id.lower()
    return "qwen3-vl-embedding" in m


def _table_set_for_model(model_id: str) -> ModelTableSet:
    m = (model_id or "").strip().lower()
    if "bge-m3" in m:
        return BGE_M3_TABLE_SET
    return QWEN_TABLE_SET


@lru_cache(maxsize=4)
def _get_sentence_transformer(model_id: str, device: str | None):
    from sentence_transformers import SentenceTransformer

    kwargs: dict[str, Any] = {"trust_remote_code": True}
    if device:
        kwargs["device"] = device
    return SentenceTransformer(model_id, **kwargs)


@lru_cache(maxsize=4)
def _get_qwen3_vl_embedder(model_id: str, device: str | None):
    from app.rag.qwen3_vl_embedding_upstream import Qwen3VLEmbedder

    return Qwen3VLEmbedder(model_name_or_path=model_id, device=device, trust_remote_code=True)


def _encode(
    embedder,
    texts: list[str],
    *,
    batch_size: int,
    model_id: str,
    on_batch: Optional[Callable[[int, int], None]] = None,
) -> list[list[float]]:
    if not texts:
        return []

    n_batches = (len(texts) + batch_size - 1) // batch_size

    if _is_qwen3_vl_embedding_model(model_id):
        out: list[list[float]] = []
        for bi, start in enumerate(range(0, len(texts), batch_size)):
            if on_batch:
                on_batch(bi + 1, n_batches)
            chunk = texts[start : start + batch_size]
            emb = embedder.process([{"text": t} for t in chunk], normalize=True)
            arr = emb.detach().cpu().float().numpy()
            out.extend(arr[i].astype("float32").tolist() for i in range(arr.shape[0]))
        return out

    out_st: list[list[float]] = []
    for bi, start in enumerate(range(0, len(texts), batch_size)):
        if on_batch:
            on_batch(bi + 1, n_batches)
        chunk = texts[start : start + batch_size]
        chunk_vecs = embedder.encode(
            chunk,
            batch_size=min(batch_size, len(chunk)),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        out_st.extend(v.astype("float32").tolist() for v in chunk_vecs)
    return out_st


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
    entity_batch_size: int,
    device: str | None,
    max_chars: int,
    overlap: int,
    progress: Optional[Callable[[str, int], None]] = None,
) -> dict[str, list[dict[str, Any]]]:
    def p(message: str, percent: int) -> None:
        if progress:
            progress(message, percent)

    table_set = _table_set_for_model(model_id)
    outputs: dict[str, list[dict[str, Any]]] = {
        table_set.profile_kor: [],
        table_set.profile_eng: [],
        table_set.evidence_kor: [],
        table_set.evidence_eng: [],
    }

    entity_batch_size = max(1, int(entity_batch_size))
    total_rows = len(rows)
    total_entity_batches = max(1, (total_rows + entity_batch_size - 1) // entity_batch_size)
    p(
        f"배치 임베딩 시작 (총 {total_rows}개 엔티티, {total_entity_batches}개 배치, 배치크기={entity_batch_size})",
        10,
    )

    resolved_device = _resolve_device(device)
    p(
        f"임베딩 모델 로드 중 (device={resolved_device}, 최초 실행 시 다운로드로 시간이 걸릴 수 있습니다)",
        16,
    )
    if _is_qwen3_vl_embedding_model(model_id):
        embedder = _get_qwen3_vl_embedder(model_id, resolved_device)
    else:
        embedder = _get_sentence_transformer(model_id, resolved_device)
    p(f"모델 준비 완료 (device={resolved_device})", 28)

    for bi, start in enumerate(range(0, total_rows, entity_batch_size), start=1):
        row_batch = rows[start : start + entity_batch_size]
        all_jobs: list[tuple[str, dict[str, Any], str]] = []

        for i, row in enumerate(row_batch):
            new_company_id = row.get("id") or row.get("external_id") or f"row-{start+i+1}"
            external_id = row.get("external_id") or ""

            for lang in ("kor", "eng"):
                ptxt = _profile_text(row, lang=lang)
                if ptxt:
                    all_jobs.append(
                        (
                            table_set.profile_kor if lang == "kor" else table_set.profile_eng,
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
                    all_jobs.append(
                        (
                            table_set.evidence_kor if lang == "kor" else table_set.evidence_eng,
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

        def _batch_pct(offset: int) -> int:
            return min(96, 28 + int(66 * ((bi - 1 + offset) / max(total_entity_batches, 1))))

        if all_jobs:
            p(f"[{bi}/{total_entity_batches}] 프로필/근거 통합 임베딩 중", _batch_pct(0))
            vectors = _encode(
                embedder,
                [t for _, _, t in all_jobs],
                batch_size=batch_size,
                model_id=model_id,
            )
            if len(vectors) != len(all_jobs):
                raise RuntimeError(
                    f"embedding mismatch: {len(all_jobs)} jobs vs {len(vectors)} vectors"
                )
            for (table, rec, _), vec in zip(all_jobs, vectors):
                rec["embedding_dim"] = len(vec)
                rec["embedding"] = vec
                outputs[table].append(rec)

        p(
            f"엔티티 배치 {bi}/{total_entity_batches} 완료 (누적 profile={len(outputs[table_set.profile_kor]) + len(outputs[table_set.profile_eng])}, evidence={len(outputs[table_set.evidence_kor]) + len(outputs[table_set.evidence_eng])})",
            _batch_pct(1),
        )

    p("배치 임베딩 완료", 96)

    return outputs


def _embedding_ddl_statements(table_set: ModelTableSet) -> list[str]:
    ddl: list[str] = ["CREATE EXTENSION IF NOT EXISTS vector"]
    for table in (table_set.profile_kor, table_set.profile_eng, table_set.evidence_kor, table_set.evidence_eng):
        ddl.append(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
              id uuid PRIMARY KEY,
              exhibitor_id uuid NOT NULL REFERENCES new_company(id) ON DELETE CASCADE,
              external_id text NULL,
              lang varchar(8) NOT NULL,
              content text NOT NULL,
              content_hash varchar(64) NOT NULL,
              embedding_dim integer NOT NULL,
              embedding vector NULL,
              model text NOT NULL,
              source_field text NULL,
              chunk_index integer NULL,
              chunk_typ varchar(32) NOT NULL,
              created_at timestamptz NOT NULL DEFAULT now(),
              updated_at timestamptz NOT NULL DEFAULT now(),
              UNIQUE (exhibitor_id, content_hash)
            )
            """
        )
        ddl.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_exhibitor_id ON {table} (exhibitor_id)")
        ddl.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_content_hash ON {table} (content_hash)")
        ddl.append(f"CREATE INDEX IF NOT EXISTS ix_{table}_chunk_typ ON {table} (chunk_typ)")
    return ddl


def _upsert_embeddings(
    results: dict[str, list[dict[str, Any]]],
    *,
    model_id: str,
    progress: Optional[Callable[[str, int], None]] = None,
) -> dict[str, int]:
    def p(message: str, percent: int) -> None:
        if progress:
            progress(message, percent)

    table_set = _table_set_for_model(model_id)
    table_specs = [
        (table_set.profile_kor, results.get(table_set.profile_kor, []), "profile"),
        (table_set.profile_eng, results.get(table_set.profile_eng, []), "profile"),
        (table_set.evidence_kor, results.get(table_set.evidence_kor, []), "evidence"),
        (table_set.evidence_eng, results.get(table_set.evidence_eng, []), "evidence"),
    ]
    counts: dict[str, int] = {
        table_set.profile_kor: 0,
        table_set.profile_eng: 0,
        table_set.evidence_kor: 0,
        table_set.evidence_eng: 0,
    }
    pending_batches: list[tuple[str, list[dict[str, Any]]]] = []

    total_tables = len(table_specs)
    for idx, (table_name, records, chunk_typ) in enumerate(table_specs, start=1):
        if not records:
            p(f"DB upsert: {table_name} (0건)", 96 + int((idx / total_tables) * 3))
            continue

        p(f"DB upsert: {table_name} ({len(records)}건)", 96 + int(((idx - 1) / total_tables) * 3))
        payloads: list[dict[str, Any]] = []
        for r in records:
            payloads.append(
                {
                    "id": r["id"],
                    "exhibitor_id": r["new_company_id"],
                    "external_id": r.get("external_id"),
                    "lang": r.get("lang") or ("kor" if table_name.endswith("_kor") else "eng"),
                    "content": r["content"],
                    "content_hash": _content_hash(r["content"]),
                    "embedding_dim": int(r["embedding_dim"]),
                    "embedding": _vector_literal(r["embedding"]),
                    "model": r["model"],
                    "source_field": r.get("source_field"),
                    "chunk_index": r.get("chunk_index"),
                    "chunk_typ": chunk_typ,
                }
            )

        insert_sql = f"""
        INSERT INTO {table_name}
          (id, exhibitor_id, external_id, lang, content, content_hash, embedding_dim, embedding, model, source_field, chunk_index, chunk_typ, created_at, updated_at)
        VALUES
          (CAST(:id AS uuid), CAST(:exhibitor_id AS uuid), :external_id, :lang, :content, :content_hash, :embedding_dim, CAST(:embedding AS vector), :model, :source_field, :chunk_index, :chunk_typ, now(), now())
        ON CONFLICT (exhibitor_id, content_hash)
        DO UPDATE SET
          external_id = EXCLUDED.external_id,
          lang = EXCLUDED.lang,
          content = EXCLUDED.content,
          embedding_dim = EXCLUDED.embedding_dim,
          embedding = EXCLUDED.embedding,
          model = EXCLUDED.model,
          source_field = EXCLUDED.source_field,
          chunk_index = EXCLUDED.chunk_index,
          chunk_typ = EXCLUDED.chunk_typ,
          updated_at = now()
        """
        pending_batches.append((insert_sql, payloads))
        counts[table_name] = len(payloads)
        p(f"DB 행 준비: {table_name} ({len(payloads)}건)", 96 + int((idx / total_tables) * 3))

    p("DB 저장 중 (DDL + upsert)…", 97)
    with engine.begin() as conn:
        for stmt in _embedding_ddl_statements(table_set):
            conn.execute(sa.text(stmt))
        for insert_sql, payloads in pending_batches:
            for start in range(0, len(payloads), _UPSERT_ROWS_PER_EXECUTE):
                chunk = payloads[start : start + _UPSERT_ROWS_PER_EXECUTE]
                conn.execute(sa.text(insert_sql), chunk)

    p("DB 저장 완료", 99)
    return counts


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


def _embed_texts(
    texts: list[str],
    *,
    model_id: str,
    device: str | None,
    batch_size: int = 32,
) -> list[list[float]]:
    resolved_device = _resolve_device(device)
    if _is_qwen3_vl_embedding_model(model_id):
        embedder = _get_qwen3_vl_embedder(model_id, resolved_device)
    else:
        embedder = _get_sentence_transformer(model_id, resolved_device)
    return _encode(embedder, texts, batch_size=batch_size, model_id=model_id)


def _embed_query_via_http(
    base_url: str,
    query: str,
    *,
    model_id: str,
    device: str | None,
    timeout_sec: int = 120,
) -> list[float]:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is empty")
    endpoint = base_url.rstrip("/") + "/v1/embed/query"
    body = urlencode(
        {
            "query": q,
            "model_id": model_id,
            "device": (device or "").strip(),
        }
    ).encode("utf-8")
    req = urllib_request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=timeout_sec) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    vec = payload.get("embedding")
    if not isinstance(vec, list) or not vec:
        raise RuntimeError("remote embed returned empty embedding")
    return [float(x) for x in vec]


def embed_query_text(
    query: str,
    *,
    model_id: str,
    device: str | None,
    remote_base_url: str | None = None,
) -> list[float]:
    q = (query or "").strip()
    if not q:
        raise ValueError("query is empty")
    base = (remote_base_url or "").strip() or os.environ.get("EMBEDDING_SERVICE_URL", "").strip()
    if base:
        return _embed_query_via_http(base, q, model_id=model_id, device=device)
    vectors = _embed_texts([q], model_id=model_id, device=device, batch_size=1)
    if not vectors:
        raise RuntimeError("failed to embed query")
    return vectors[0]


def search_embedding_tables(
    *,
    query_embedding: list[float],
    model_id: str,
    top_k: int,
    lang: str,
    chunk_type: str,
) -> list[dict[str, Any]]:
    top_k = max(1, int(top_k))

    table_set = _table_set_for_model(model_id)
    all_specs = [
        (table_set.profile_kor, "profile", "kor"),
        (table_set.profile_eng, "profile", "eng"),
        (table_set.evidence_kor, "evidence", "kor"),
        (table_set.evidence_eng, "evidence", "eng"),
    ]

    selected: list[tuple[str, str, str]] = []
    for table_name, typ, table_lang in all_specs:
        if chunk_type != "all" and chunk_type != typ:
            continue
        if lang != "all" and lang != table_lang:
            continue
        selected.append((table_name, typ, table_lang))

    if not selected:
        return []

    union_parts: list[str] = []
    for table_name, typ, table_lang in selected:
        union_parts.append(
            f"""
            (
              SELECT
                '{table_name}' AS table_name,
                exhibitor_id::text AS exhibitor_id,
                external_id,
                lang,
                model,
                '{typ}' AS chunk_typ,
                source_field,
                chunk_index,
                content,
                (embedding <=> CAST(:embedding AS vector)) AS distance
              FROM {table_name}
              WHERE embedding IS NOT NULL
              ORDER BY embedding <=> CAST(:embedding AS vector)
              LIMIT :per_table_limit
            )
            """
        )

    sql = f"""
    SELECT
      table_name,
      exhibitor_id,
      external_id,
      lang,
      model,
      chunk_typ,
      source_field,
      chunk_index,
      content,
      distance,
      (1 - distance) AS score
    FROM (
      {" UNION ALL ".join(union_parts)}
    ) ranked
    ORDER BY distance ASC
    LIMIT :top_k
    """

    per_table_limit = max(top_k, 50)
    params = {
        "embedding": _vector_literal(query_embedding),
        "per_table_limit": per_table_limit,
        "top_k": top_k,
    }
    with engine.connect() as conn:
        rows = conn.execute(sa.text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def build_korean_search_answer(query: str, results: list[dict[str, Any]]) -> str:
    q = (query or "").strip()
    if not results:
        return f"'{q}'와(과) 관련된 업체를 찾지 못했습니다. 검색어를 더 구체적으로 입력해 주세요."

    # Prefer profile chunks so the answer area shows company profile-like data directly.
    profiles = [r for r in results if (r.get("chunk_typ") == "profile")]
    candidates = profiles if profiles else results

    lines: list[str] = [f"[검색어] {q}", "[프로필 데이터]"]
    seen_external_ids: set[str] = set()
    for r in candidates:
        ext = (r.get("external_id") or "").strip() or "외부 ID 없음"
        if ext in seen_external_ids:
            continue
        seen_external_ids.add(ext)
        content = (r.get("content") or "").strip()
        if not content:
            continue
        score = r.get("score")
        score_text = f"{float(score):.3f}" if isinstance(score, (int, float)) else "-"
        lines.append(f"- external_id: {ext} (score={score_text}, lang={r.get('lang')})")
        lines.append(content)
        if len(seen_external_ids) >= 3:
            break

    if len(lines) <= 2:
        return f"[검색어] {q}\n[프로필 데이터]\n- 표시할 profile 데이터가 없습니다."
    return "\n".join(lines)
