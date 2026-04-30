"""KPRINT RAG용 임베딩 파이프라인 (DB 조회 → 벡터 생성 → pgvector UPSERT).

이 모듈은 FastAPI와 분리되어 있으며, **배치 임베딩**과 **쿼리 임베딩·벡터 검색**을 담당한다.

배치 임베딩(메인 흐름)이 거치는 단계:
  1) DB에서 원본 행 로드 — `_fetch_kprint_exhibitor_rows` / `_fetch_kprint_exhibit_item_rows`
  2) 행마다 profile 텍스트·evidence 청크 구성 — `_profile_text_for_entity`, `_evidence_chunks_for_entity`
  3) 모델로 텍스트 벡터화 — `_build_embeddings` 내부에서 `_encode` 호출
  4) 네 개의 임베딩 테이블(kor/eng × profile/evidence)에 UPSERT — `_upsert_embeddings`
  (선행) pgvector 확장 보장 — `_embedding_ddl_statements`

검색(RAG 조회) 흐름:
  - 질문 문장 벡터: `embed_query_text` → (원격이면 HTTP, 아니면 로컬 `_embed_texts`)
  - 유사도 검색: `search_embedding_tables` (테이블 UNION + `<=>` 거리)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from urllib import request as urllib_request
from urllib.error import HTTPError
from urllib.parse import urlencode
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal, Optional

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
    """한 엔티티(참가업체 또는 전시품)에 대응하는 4개 임베딩 테이블 이름 묶음."""

    profile_kor: str
    profile_eng: str
    evidence_kor: str
    evidence_eng: str


@dataclass(frozen=True)
class KprintModelTableBundle:
    """참가업체 + 전시품 두 종류의 테이블 세트를 한 번에 들고 다니는 구조."""

    exhibitor: ModelTableSet
    exhibit_item: ModelTableSet


KPRINT_EXHIBITOR_QWEN = ModelTableSet(
    profile_kor="kprint_exhibitor_profile_embedding_qwen3_0_6b_kor",
    profile_eng="kprint_exhibitor_profile_embedding_qwen3_0_6b_eng",
    evidence_kor="kprint_exhibitor_evidence_embedding_qwen3_0_6b_kor",
    evidence_eng="kprint_exhibitor_evidence_embedding_qwen3_0_6b_eng",
)
KPRINT_EXHIBIT_ITEM_QWEN = ModelTableSet(
    profile_kor="kprint_exhibit_item_profile_embedding_qwen3_0_6b_kor",
    profile_eng="kprint_exhibit_item_profile_embedding_qwen3_0_6b_eng",
    evidence_kor="kprint_exhibit_item_evidence_embedding_qwen3_0_6b_kor",
    evidence_eng="kprint_exhibit_item_evidence_embedding_qwen3_0_6b_eng",
)

# Backward-compatible aliases.
QWEN_TABLE_SET = KPRINT_EXHIBITOR_QWEN
PROFILE_TABLE_KOR = KPRINT_EXHIBITOR_QWEN.profile_kor
PROFILE_TABLE_ENG = KPRINT_EXHIBITOR_QWEN.profile_eng
EVIDENCE_TABLE_KOR = KPRINT_EXHIBITOR_QWEN.evidence_kor
EVIDENCE_TABLE_ENG = KPRINT_EXHIBITOR_QWEN.evidence_eng


def _kprint_bundle_for_model(_model_id: str = "") -> KprintModelTableBundle:
    """모델 ID에 상관없이 KPRINT용 Qwen3 0.6B 테이블 번들을 반환한다 (테이블명 고정)."""
    return KprintModelTableBundle(KPRINT_EXHIBITOR_QWEN, KPRINT_EXHIBIT_ITEM_QWEN)


def _kprint_table_set_for_entity(
    entity: Literal["exhibitor", "exhibit_item"], model_id: str
) -> ModelTableSet:
    """엔티티 종류(참가업체 vs 전시품)에 맞는 4테이블 세트만 골라 반환한다."""
    bundle = _kprint_bundle_for_model(model_id)
    return bundle.exhibit_item if entity == "exhibit_item" else bundle.exhibitor


def _kprint_parent_sql_table(entity: Literal["exhibitor", "exhibit_item"]) -> str:
    """임베딩 행이 참조하는 원본 테이블명(로깅/DDL 호환용)."""
    return "kprint_exhibit_item" if entity == "exhibit_item" else "kprint_exhibitor"

_UPSERT_ROWS_PER_EXECUTE = 1000


def _resolve_device(device: str | None) -> str | None:
    """요청 device를 정규화한다. MPS는 사용 가능할 때만, 아니면 CPU로 떨어진다."""
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
    """스크립트 단독 실행 시 `.env`에서 DB URL만 읽기 위한 최소 설정."""

    embedding_database_url: Optional[str] = None
    database_url: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(RAG_DIR / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def _resolve_database_url() -> str:
    """동기 SQLAlchemy 엔진용 Postgres URL. Docker 안/밖에 따라 host(db vs localhost)를 보정한다."""
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


engine = sa.create_engine(_resolve_database_url(), future=True, pool_pre_ping=True)  # 배치/검색 공용 동기 DB 엔진

# 참가업체·전시품 테이블에서 profile(요약) vs evidence(나머지 컬럼 청크)로 나눌 때 쓰는 컬럼 목록
KPRINT_EXHIBITOR_PROFILE_KOR: tuple[str, ...] = (
    "company_name_kor",
    "exhibit_year",
    "exhibition_category_label",
    "booth_number",
    "homepage",
    "country_code",
    "country_label_kor",
    "exhibit_hall_label_kor",
    "exhibit_hall_code",
)
KPRINT_EXHIBITOR_PROFILE_ENG: tuple[str, ...] = (
    "company_name_eng",
    "exhibit_year",
    "exhibition_category_label",
    "booth_number",
    "homepage",
    "country_code",
    "country_label_eng",
    "exhibit_hall_label_eng",
    "exhibit_hall_code",
)
KPRINT_EXHIBITOR_PROFILE_ALL = set(KPRINT_EXHIBITOR_PROFILE_KOR) | set(KPRINT_EXHIBITOR_PROFILE_ENG)

KPRINT_EXHIBIT_ITEM_PROFILE_KOR: tuple[str, ...] = (
    "item_main_category_label_kor",
    "item_main_category",
    "item_sub_category",
    "item_sub_category_label_kor",
    "product_name_kor",
    "search_keywords_kor",
)
KPRINT_EXHIBIT_ITEM_PROFILE_ENG: tuple[str, ...] = (
    "item_main_category_label_eng",
    "item_main_category",
    "item_sub_category",
    "item_sub_category_label_eng",
    "product_name_eng",
    "search_keywords_eng",
)
KPRINT_EXHIBIT_ITEM_PROFILE_ALL = set(KPRINT_EXHIBIT_ITEM_PROFILE_KOR) | set(KPRINT_EXHIBIT_ITEM_PROFILE_ENG)


def _safe_str(value: Any) -> str:
    """DB/CSV 값을 안전한 문자열로 정리 (None → 빈 문자열, strip)."""
    if value is None:
        return ""
    return str(value).strip()


def _is_kor_col(name: str) -> bool:
    """컬럼명이 한국어 필드인지 (`_kor` 포함 여부)."""
    return "_kor" in name


def _is_eng_col(name: str) -> bool:
    """컬럼명이 영어 필드인지 (`_eng` 포함 여부)."""
    return "_eng" in name


def _chunk_text(text: str, *, max_chars: int, overlap: int) -> list[str]:
    """긴 텍스트를 evidence용으로 겹침(overlap)을 두고 잘라 여러 청크로 만든다."""
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
    """동일 내용 UPSERT/중복 방지용 SHA256 해시."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _vector_literal(vec: list[float]) -> str:
    """pgvector SQL 리터럴 형태 `[0.1,0.2,...]` 문자열로 변환."""
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"


def _is_qwen3_vl_embedding_model(model_id: str) -> bool:
    """멀티모달 Qwen3-VL 임베딩 경로인지 판별 (일반 SentenceTransformer와 분기)."""
    m = model_id.lower()
    return "qwen3-vl-embedding" in m


@lru_cache(maxsize=4)
def _get_sentence_transformer(model_id: str, device: str | None):
    """SentenceTransformer 모델을 한 번 로드해 캐시한다 (일반 텍스트 임베딩)."""
    from sentence_transformers import SentenceTransformer

    kwargs: dict[str, Any] = {"trust_remote_code": True}
    if device:
        kwargs["device"] = device
    return SentenceTransformer(model_id, **kwargs)


@lru_cache(maxsize=4)
def _get_qwen3_vl_embedder(model_id: str, device: str | None):
    """Qwen3-VL 임베딩 전용 래퍼를 로드한다 (텍스트만 넣어도 벡터 생성)."""
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
    """문장 리스트를 float32 벡터 리스트로 배치 인코딩 (Qwen3-VL vs ST 경로 분기)."""
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


def _profile_text_from_columns(row: dict[str, str], cols: tuple[str, ...]) -> str:
    """지정 컬럼만 `이름: 값` 줄로 이어 붙여 profile 한 덩어리 텍스트를 만든다."""
    lines = [f"{c}: {_safe_str(row.get(c))}" for c in cols if _safe_str(row.get(c))]
    return "\n".join(lines).strip()


def _profile_text_for_entity(
    row: dict[str, str], *, lang: str, entity: Literal["exhibitor", "exhibit_item"]
) -> str:
    """엔티티·언어(kor/eng)에 맞는 profile 컬럼 집합으로 `_profile_text_from_columns` 호출."""
    if entity == "exhibit_item":
        cols = KPRINT_EXHIBIT_ITEM_PROFILE_KOR if lang == "kor" else KPRINT_EXHIBIT_ITEM_PROFILE_ENG
    else:
        cols = KPRINT_EXHIBITOR_PROFILE_KOR if lang == "kor" else KPRINT_EXHIBITOR_PROFILE_ENG
    return _profile_text_from_columns(row, cols)


def _evidence_chunks_for_entity(
    row: dict[str, str],
    *,
    lang: str,
    max_chars: int,
    overlap: int,
    entity: Literal["exhibitor", "exhibit_item"],
) -> list[dict[str, Any]]:
    """profile에 쓴 컬럼·반대 언어 컬럼을 제외한 나머지를 필드별로 청크해 evidence 목록으로 만든다."""
    profile_all = KPRINT_EXHIBIT_ITEM_PROFILE_ALL if entity == "exhibit_item" else KPRINT_EXHIBITOR_PROFILE_ALL
    skip = profile_all | {"id"}
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
    koba_entity: Literal["exhibitor", "exhibit_item"] = "exhibitor",
    progress: Optional[Callable[[str, int], None]] = None,
) -> dict[str, list[dict[str, Any]]]:
    """배치 임베딩의 핵심: DB 행 리스트 → 4테이블별 레코드(텍스트+벡터) 딕셔너리.

    내부 단계 요약:
      A. 출력 버킷 초기화 (profile_kor/eng, evidence_kor/eng 테이블명 키)
      B. device 결정 후 임베더 로드 (Qwen3-VL 또는 SentenceTransformer)
      C. `entity_batch_size`만큼 행을 묶어 반복:
           C1. 각 행·kor/eng에 대해 profile 1건 + evidence N건을 `all_jobs`에 적재
           C2. 모든 job의 본문을 한꺼번에 `_encode` → 벡터를 각 레코드에 붙임
      D. 테이블명 → 레코드 리스트 맵을 반환 (`_upsert_embeddings` 입력)
    """
    def p(message: str, percent: int) -> None:
        if progress:
            progress(message, percent)

    table_set = _kprint_table_set_for_entity(koba_entity, model_id)
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
            entity_id = row.get("id") or row.get("external_id") or f"row-{start+i+1}"
            external_id = row.get("external_id") or ""

            for lang in ("kor", "eng"):
                ptxt = _profile_text_for_entity(row, lang=lang, entity=koba_entity)
                if ptxt:
                    all_jobs.append(
                        (
                            table_set.profile_kor if lang == "kor" else table_set.profile_eng,
                            {
                                "id": str(uuid.uuid4()),
                                "entity_id": entity_id,
                                "external_id": external_id,
                                "lang": lang,
                                "content": ptxt,
                                "model": model_id,
                            },
                            ptxt,
                        )
                    )

                for ev in _evidence_chunks_for_entity(
                    row,
                    lang=lang,
                    max_chars=max_chars,
                    overlap=overlap,
                    entity=koba_entity,
                ):
                    all_jobs.append(
                        (
                            table_set.evidence_kor if lang == "kor" else table_set.evidence_eng,
                            {
                                "id": str(uuid.uuid4()),
                                "entity_id": entity_id,
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


def _embedding_ddl_statements(
    _table_set: ModelTableSet,
    *,
    parent_table: str | None = None,
    _parent_table: str | None = None,
) -> list[str]:
    """UPSERT 전에 실행할 DDL 문장 목록. 실제 테이블 생성은 Alembic 담당, 여기서는 pgvector 확장만 보장.

    Note:
    - Older call sites used `parent_table=...`
    - Older definitions used `_parent_table=...`
    We accept both keywords to avoid runtime crashes during rolling upgrades.
    """
    return ["CREATE EXTENSION IF NOT EXISTS vector"]


def _upsert_embeddings(
    results: dict[str, list[dict[str, Any]]],
    *,
    model_id: str,
    koba_entity: Literal["exhibitor", "exhibit_item"] = "exhibitor",
    progress: Optional[Callable[[str, int], None]] = None,
) -> dict[str, int]:
    """`_build_embeddings` 결과를 네 임베딩 테이블에 ON CONFLICT UPSERT하고 테이블별 건수를 반환."""
    def p(message: str, percent: int) -> None:
        if progress:
            progress(message, percent)

    table_set = _kprint_table_set_for_entity(koba_entity, model_id)
    parent_table = _kprint_parent_sql_table(koba_entity)
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
                    "entity_id": r["entity_id"],
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
          (id, entity_id, external_id, lang, content, content_hash, embedding_dim, embedding, model, source_field, chunk_index, chunk_typ, created_at, updated_at)
        VALUES
          (CAST(:id AS uuid), CAST(:entity_id AS uuid), :external_id, :lang, :content, :content_hash, :embedding_dim, CAST(:embedding AS vector), :model, :source_field, :chunk_index, :chunk_typ, now(), now())
        ON CONFLICT (entity_id, content_hash)
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
        for stmt in _embedding_ddl_statements(table_set, parent_table=parent_table):
            conn.execute(sa.text(stmt))
        for insert_sql, payloads in pending_batches:
            for start in range(0, len(payloads), _UPSERT_ROWS_PER_EXECUTE):
                chunk = payloads[start : start + _UPSERT_ROWS_PER_EXECUTE]
                conn.execute(sa.text(insert_sql), chunk)

    p("DB 저장 완료", 99)
    return counts


def _row_from_mapping(record: dict[str, Any], table: sa.Table) -> dict[str, str]:
    """SQLAlchemy 매핑 행을 임베딩 파이프라인용 `dict[str, str]`로 정규화 (리스트는 join)."""
    row: dict[str, str] = {}
    for col in table.columns:
        value = record.get(col.name)
        if isinstance(value, list):
            row[col.name] = ", ".join(str(v) for v in value)
        else:
            row[col.name] = "" if value is None else str(value)
    return row


def _fetch_kprint_exhibitor_rows(limit: int | None) -> list[dict[str, str]]:
    """`kprint_exhibitor` 전체(또는 limit)를 읽어 임베딩 입력 행 리스트로 반환."""
    metadata = sa.MetaData()
    tbl = sa.Table("kprint_exhibitor", metadata, autoload_with=engine)
    stmt = sa.select(tbl)
    if "created_at" in tbl.c:
        stmt = stmt.order_by(tbl.c.created_at.asc())
    if limit is not None:
        stmt = stmt.limit(limit)
    rows: list[dict[str, str]] = []
    with engine.connect() as conn:
        for record in conn.execute(stmt).mappings().all():
            rows.append(_row_from_mapping(dict(record), tbl))
    return rows


def _fetch_kprint_exhibit_item_rows(limit: int | None) -> list[dict[str, str]]:
    """`kprint_exhibit_item` 전체(또는 limit)를 읽어 임베딩 입력 행 리스트로 반환."""
    metadata = sa.MetaData()
    tbl = sa.Table("kprint_exhibit_item", metadata, autoload_with=engine)
    stmt = sa.select(tbl)
    if "created_at" in tbl.c:
        stmt = stmt.order_by(tbl.c.created_at.asc())
    if limit is not None:
        stmt = stmt.limit(limit)
    rows: list[dict[str, str]] = []
    with engine.connect() as conn:
        for record in conn.execute(stmt).mappings().all():
            rows.append(_row_from_mapping(dict(record), tbl))
    return rows


def _embed_texts(
    texts: list[str],
    *,
    model_id: str,
    device: str | None,
    batch_size: int = 32,
) -> list[list[float]]:
    """임의 텍스트 리스트를 로컬 모델로만 임베딩 (쿼리/배치 공용 저수준 API)."""
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
    """별도 임베딩 서비스 HTTP `/v1/embed/query`로 질의 벡터 한 개를 받아온다."""
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


def _embed_queries_via_http(
    base_url: str,
    queries: list[str],
    *,
    model_id: str,
    device: str | None,
    timeout_sec: int = 120,
) -> list[list[float]]:
    """별도 임베딩 서비스 `/v1/embed/queries`로 질의 여러 줄을 한 번에 벡터화 (서버 단일 배치)."""
    if not queries:
        return []
    endpoint = base_url.rstrip("/") + "/v1/embed/queries"
    body = urlencode(
        {
            "queries": json.dumps(queries, ensure_ascii=False),
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
    rows = payload.get("embeddings")
    if not isinstance(rows, list) or len(rows) != len(queries):
        raise RuntimeError("remote embed/queries returned invalid payload")
    out: list[list[float]] = []
    for row in rows:
        if not isinstance(row, list) or not row:
            raise RuntimeError("remote embed/queries returned empty row")
        out.append([float(x) for x in row])
    return out


def embed_query_text(
    query: str,
    *,
    model_id: str,
    device: str | None,
    remote_base_url: str | None = None,
) -> list[float]:
    """RAG 검색용 질문 한 줄을 벡터로 변환. URL/환경변수가 있으면 원격, 없으면 로컬 `_embed_texts`."""
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


def embed_queries_text(
    queries: list[str],
    *,
    model_id: str,
    device: str | None,
    remote_base_url: str | None = None,
) -> list[list[float]]:
    """RAG 다중 쿼리용: 순서 유지, 원격이면 한 HTTP로 배치, 없으면 로컬 `_embed_texts` 배치."""
    cleaned = [(q or "").strip() for q in queries]
    if not cleaned:
        return []
    base = (remote_base_url or "").strip() or os.environ.get("EMBEDDING_SERVICE_URL", "").strip()
    if base:
        try:
            return _embed_queries_via_http(base, cleaned, model_id=model_id, device=device)
        except HTTPError as e:
            if e.code == 404:
                return [
                    _embed_query_via_http(base, q, model_id=model_id, device=device) for q in cleaned
                ]
            raise
    n = len(cleaned)
    vectors = _embed_texts(cleaned, model_id=model_id, device=device, batch_size=min(32, max(1, n)))
    if len(vectors) != n:
        raise RuntimeError("failed to embed queries batch")
    return vectors


def search_embedding_tables(
    *,
    query_embedding: list[float],
    model_id: str,
    top_k: int,
    lang: str,
    chunk_type: str,
    entity_scope: str = "all",
    per_table_limit: int | None = None,
) -> list[dict[str, Any]]:
    """질의 벡터와 코사인 거리(`<=>`)로 여러 임베딩 테이블을 UNION 검색해 상위 `top_k` 행을 반환."""
    top_k = max(1, int(top_k))

    bundle = _kprint_bundle_for_model(model_id)
    all_specs: list[tuple[str, str, str]] = []
    scopes = {"all", "company", "product"}
    scope = (entity_scope or "all").strip().lower()
    if scope not in scopes:
        scope = "all"
    if scope == "company":
        table_sets = (bundle.exhibitor,)
    elif scope == "product":
        table_sets = (bundle.exhibit_item,)
    else:
        table_sets = (bundle.exhibitor, bundle.exhibit_item)

    for ts in table_sets:
        all_specs.extend(
            [
                (ts.profile_kor, "profile", "kor"),
                (ts.profile_eng, "profile", "eng"),
                (ts.evidence_kor, "evidence", "kor"),
                (ts.evidence_eng, "evidence", "eng"),
            ]
        )

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
                entity_id::text AS exhibitor_id,
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

    if per_table_limit is None:
        # UNION 브랜치마다 상한이 너무 크면(예: 50 고정) pgvector 정렬 비용이 커진다.
        per_table_limit = min(max(top_k * 5, 14), 36)
    else:
        per_table_limit = max(1, int(per_table_limit))
    params = {
        "embedding": _vector_literal(query_embedding),
        "per_table_limit": per_table_limit,
        "top_k": top_k,
    }
    with engine.connect() as conn:
        rows = conn.execute(sa.text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def split_search_results_profile_evidence(
    results: list[dict[str, Any]],
    *,
    max_profiles: int = 4,
    max_evidence: int = 8,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """RRF 순서를 유지한 채 profile은 external_id 기준 중복 제거, 나머지는 evidence 취급."""
    profiles: list[dict[str, Any]] = []
    seen_ext: set[str] = set()
    for r in results:
        if r.get("chunk_typ") != "profile":
            continue
        ext = str(r.get("external_id") or "").strip()
        if ext and ext in seen_ext:
            continue
        if ext:
            seen_ext.add(ext)
        profiles.append(r)
        if len(profiles) >= max_profiles:
            break

    evidence: list[dict[str, Any]] = []
    for r in results:
        if r.get("chunk_typ") == "profile":
            continue
        evidence.append(r)
        if len(evidence) >= max_evidence:
            break
    return profiles, evidence


def format_search_results_for_llm_context(results: list[dict[str, Any]]) -> str:
    """OpenAI 등 답변 생성용: 프로필은 항목별 블록, evidence는 한 줄 요약 (의도/점수 메타 없음)."""
    profiles, evidence = split_search_results_profile_evidence(results)
    blocks: list[str] = []

    if profiles:
        blocks.append("【프로필】 (전시 참가사·전시품 요약)")
        for i, r in enumerate(profiles, start=1):
            ext = (r.get("external_id") or "").strip() or "(식별자 없음)"
            sf = (r.get("source_field") or "").strip()
            body = (r.get("content") or "").strip()
            if len(body) > 1200:
                body = body[:1200].rstrip() + "…"
            head = f"— 항목 {i} · {ext}"
            if sf:
                head += f" · 출처 필드: {sf}"
            blocks.append(head + "\n" + body)

    if evidence:
        blocks.append("\n【추가 근거】 (상세·증빙 텍스트 요약, 한 줄씩)")
        for i, r in enumerate(evidence, start=1):
            ext = (r.get("external_id") or "").strip() or "-"
            sf = (r.get("source_field") or "").strip() or "-"
            typ = (r.get("chunk_typ") or "").strip() or "-"
            c = (r.get("content") or "").strip().replace("\n", " ")
            if len(c) > 300:
                c = c[:300].rstrip() + "…"
            blocks.append(f"· [{i}] 유형={typ}, 식별자={ext}, 필드={sf}\n  {c}")

    out = "\n".join(blocks).strip()
    return out or "(검색 결과 본문이 비어 있습니다.)"


def build_korean_search_answer(query: str, results: list[dict[str, Any]]) -> str:
    """검색 결과를 채팅에 바로 넣기 좋은 한국어 안내 문구로 만든다 (템플릿/폴백용)."""
    q = (query or "").strip()
    if not results:
        return f"「{q}」에 맞는 정보를 찾지 못했습니다. 다른 표현으로 검색해 보시겠어요?"

    profiles, evidence = split_search_results_profile_evidence(results)
    lines: list[str] = [
        f"질문하신「{q}」과 가장 잘 맞는 저장 데이터를 아래처럼 정리했습니다.",
        "",
    ]

    if profiles:
        lines.append("■ 관련 프로필")
        for r in profiles:
            ext = (r.get("external_id") or "").strip() or "식별자 없음"
            body = (r.get("content") or "").strip()
            if not body:
                continue
            lines.append(f"  · {ext}")
            for part in body.split("\n"):
                part = part.strip()
                if part:
                    lines.append(f"    {part}")
        lines.append("")

    if evidence:
        lines.append("■ 추가로 참고한 내용 (요약)")
        for r in evidence[:6]:
            ext = (r.get("external_id") or "").strip() or "-"
            sf = (r.get("source_field") or "").strip()
            c = (r.get("content") or "").strip().replace("\n", " ")
            if len(c) > 200:
                c = c[:200].rstrip() + "…"
            tail = f" ({sf})" if sf else ""
            lines.append(f"  · {ext}{tail}: {c}")
        lines.append("")

    lines.append("위 내용만 근거로 답변했습니다. 더 구체적인 업체명·제품명이 있으면 알려 주세요.")
    if not profiles and not evidence:
        return f"「{q}」에 대해 표시할 검색 본문이 없습니다."
    return "\n".join(lines).rstrip()


# 구버전 import/호출자 호환용 별칭 (동일 함수를 가리킴).
_koba_bundle_for_model = _kprint_bundle_for_model
_koba_table_set_for_entity = _kprint_table_set_for_entity
_koba_parent_sql_table = _kprint_parent_sql_table
_fetch_koba_exhibitor_rows = _fetch_kprint_exhibitor_rows
_fetch_koba_exhibit_item_rows = _fetch_kprint_exhibit_item_rows
