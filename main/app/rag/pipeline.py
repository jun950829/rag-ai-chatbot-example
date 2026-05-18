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

import copy
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

from app.core.logger import get_logger

logger = get_logger(__name__)
from pydantic_settings import BaseSettings, SettingsConfigDict

# app/rag/pipeline.py -> repo root is two levels above this file
RAG_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = RAG_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.sync_url import to_sync_postgres_dsn

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
    """동기 SQLAlchemy 엔진용 Postgres URL. async DSN 은 ``to_sync_postgres_dsn`` 으로 맞춘다.

    우선순위: 프로세스 환경 ``DATABASE_URL`` / ``POSTGRES_DSN`` (Docker·워커에서 가장 확실) →
    ``_EmbeddingLocalSettings`` 파일 → 마지막 ``get_settings()`` (임베딩 호스트에서는 기본 ``@db`` 가
    잡히지 않도록 env 가 없을 때만).
    """
    in_container = (PROJECT_ROOT / ".dockerenv").exists() or Path("/.dockerenv").exists()

    url = (os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DSN") or "").strip() or None
    if not url:
        local = _EmbeddingLocalSettings()
        url = (
            ((local.embedding_database_url or local.database_url or "").strip()) or None
        )
    if not url:
        try:
            from app.core.config import get_settings

            url = (get_settings().database_url or "").strip() or None
        except Exception:
            url = None

    if not url:
        if in_container:
            return "postgresql+psycopg://postgres:postgres@postgres:5432/chatbot"
        return "postgresql+psycopg://postgres:postgres@localhost:5432/rag_template"

    if "@db:" in url and not in_container:
        url = url.replace("@db:", "@localhost:")
    elif "@localhost:" in url and in_container:
        url = url.replace("@localhost:", "@db:")
    return to_sync_postgres_dsn(url)


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


@lru_cache(maxsize=16)
def _get_sentence_transformer(model_id: str, device: str | None, backend: str):
    """SentenceTransformer 모델을 한 번 로드해 캐시한다 (일반 텍스트 임베딩)."""
    from sentence_transformers import SentenceTransformer

    kwargs: dict[str, Any] = {"trust_remote_code": True}
    if device:
        kwargs["device"] = device
    _be = (backend or "").strip().lower()
    if _be:
        kwargs["backend"] = _be
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
        embedder = _get_sentence_transformer(
            model_id,
            resolved_device,
            (os.environ.get("SENTENCE_TRANSFORMERS_BACKEND") or "").strip().lower(),
        )
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
    """임의 텍스트 리스트 임베딩 (로컬 모델 우선, 미설치 시 OpenAI 폴백)."""
    if not texts:
        return []
    resolved_device = _resolve_device(device)
    try:
        if _is_qwen3_vl_embedding_model(model_id):
            embedder = _get_qwen3_vl_embedder(model_id, resolved_device)
        else:
            embedder = _get_sentence_transformer(
                model_id,
                resolved_device,
                (os.environ.get("SENTENCE_TRANSFORMERS_BACKEND") or "").strip().lower(),
            )
        return _encode(embedder, texts, batch_size=batch_size, model_id=model_id)
    except ImportError:
        # 경량 배포(EC2)에서 sentence-transformers/transformers 미설치 시 OpenAI 임베딩으로 자동 폴백.
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
        embed_model = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small").strip()
        client = OpenAI(api_key=api_key, base_url=base_url)
        out: list[list[float]] = []
        eff_batch = max(1, min(int(batch_size or 1), 128))
        for start in range(0, len(texts), eff_batch):
            chunk = texts[start : start + eff_batch]
            resp = client.embeddings.create(model=embed_model, input=chunk)
            rows = sorted(resp.data, key=lambda d: d.index)
            out.extend([[float(x) for x in r.embedding] for r in rows])
        if len(out) != len(texts):
            raise RuntimeError("openai embedding batch size mismatch")
        return out


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


# --- 사용자 응답·LLM 컨텍스트 전용: 검색 row 정리(플레이스홀더 제거·저품질 제외). 내부 사유는 로그만. ---
_RAG_USER_PLACEHOLDER_LOWER = frozenset(
    {"", ".", "-", "null", "none", "n/a", "na", "undefined", "…", "...", "[empty]"}
)
# 임베딩/품질 파이프라인에서 섞인 디버그 문구(부분 일치 시 본문 신뢰 하지 않음)
_RAG_USER_DEBUG_SUBSTRINGS = (
    "insufficient detail to rank",
    "insufficient detail",
    "not enough information",
    "only entry with full",
    "only entry with",
    "reference entry",
)


def _rag_user_row_effective_score(row: dict[str, Any]) -> float:
    try:
        return float(row.get("best_score", row.get("score", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _rag_scalar_clean_for_user(v: Any) -> str | None:
    """플레이스홀더·디버그 문구가 섞인 문자열은 None으로 본다."""

    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        s = str(v).strip()
        return s or None
    s = str(v).replace("\u0000", "").strip()
    if not s:
        return None
    low = s.lower()
    if low in _RAG_USER_PLACEHOLDER_LOWER:
        return None
    for ph in _RAG_USER_DEBUG_SUBSTRINGS:
        if ph in low:
            return None
    return s


def _sanitize_entity_detail_dict(d: dict[str, Any]) -> dict[str, Any]:
    """entity_detail에서 플레이스홀더 값 제거(키는 유지해도 되나 None/빈은 pop)."""

    out: dict[str, Any] = {}
    for k, v in d.items():
        if k == "major_products" and isinstance(v, list):
            cleaned = [_rag_scalar_clean_for_user(x) for x in v]
            lst = [x for x in cleaned if x]
            if lst:
                out[k] = lst
            continue
        if isinstance(v, dict):
            nested = _sanitize_entity_detail_dict(v)
            if nested:
                out[k] = nested
            continue
        cv = _rag_scalar_clean_for_user(v)
        if cv is not None:
            out[k] = cv
    return out


def _entity_detail_substance_chars(d: dict[str, Any]) -> int:
    """답변에 쓸 만한 텍스트 양(대략적)."""

    et = str(d.get("entity_type") or "").strip().lower()
    if et not in ("product", "company"):
        et = "product" if (d.get("product_name") or "").strip() else "company"

    prod_keys = (
        "product_name",
        "description",
        "one_liner",
        "manufacturer",
        "model_name",
        "category",
        "features",
        "location",
        "company_name",
        "contact",
        "website",
    )
    co_keys = (
        "company_name",
        "description",
        "one_liner",
        "hall",
        "booth",
        "category",
        "contact",
        "website",
        "address",
    )
    keys = prod_keys if et == "product" else co_keys
    n = 0
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            n += len(v.strip())
    mp = d.get("major_products")
    if isinstance(mp, list):
        for x in mp:
            if isinstance(x, str) and x.strip():
                n += len(x.strip())
    return n


def _row_has_user_substance_after_clean(content: str | None, ed: dict[str, Any] | None) -> bool:
    c = (content or "").strip()
    c_eff = len(c) >= 12
    if not ed:
        return c_eff
    name_ok = False
    et = str(ed.get("entity_type") or "").strip().lower()
    if et == "product":
        pn = ed.get("product_name")
        name_ok = isinstance(pn, str) and len(pn.strip()) >= 2
    else:
        cn = ed.get("company_name")
        name_ok = isinstance(cn, str) and len(cn.strip()) >= 2
    sub = _entity_detail_substance_chars(ed)
    return sub >= 8 or (name_ok and sub >= 2) or c_eff


def sanitize_rag_results_for_user(
    results: list[dict[str, Any]] | None,
    *,
    min_best_score: float = 0.0,
) -> list[dict[str, Any]]:
    """벡터 검색·직접 조회 결과를 사용자 답변/LLM 컨텍스트용으로 정리한다.

    - 점수 하한선(설정 가능, 0이면 비활성화)
    - ``.``/``-``/``null`` 등 플레이스홀더 필드 제거
    - 실질 정보가 거의 없는 row 제외
    - 스키마·키 구조는 유지(행 단위로만 드랍 또는 필드 정리)

    저품질로 제외된 사유는 ``logger.warning`` 으로만 남긴다.
    """

    out: list[dict[str, Any]] = []
    floor = float(min_best_score or 0.0)
    for r in results or []:
        row = dict(r)
        ext = str(row.get("external_id") or "").strip()
        eff_sc = _rag_user_row_effective_score(row)
        if floor > 0 and eff_sc < floor:
            logger.warning(
                "RAG 사용자 응답용 row 제외: score_below_threshold external_id=%s effective_score=%s floor=%s",
                ext or "-",
                eff_sc,
                floor,
            )
            continue

        raw_content = row.get("content")
        content_s = raw_content if isinstance(raw_content, str) else (str(raw_content) if raw_content is not None else "")
        cl = content_s.strip().lower()
        if any(p in cl for p in _RAG_USER_DEBUG_SUBSTRINGS):
            logger.warning(
                "RAG 사용자 응답용 row 제외: debug_phrase_in_content external_id=%s",
                ext or "-",
            )
            continue

        ed_in = row.get("entity_detail")
        ed_clean: dict[str, Any] | None = None
        if isinstance(ed_in, dict):
            ed_clean = _sanitize_entity_detail_dict(ed_in)

        content_clean = _rag_scalar_clean_for_user(content_s)
        row["content"] = content_clean if content_clean is not None else ""

        if isinstance(ed_in, dict):
            row["entity_detail"] = ed_clean if ed_clean else None
            if not ed_clean:
                logger.warning(
                    "RAG 사용자 응답용 entity_detail 플레이스홀더만 남음 — 본문·점수 기준 검사 진행 external_id=%s",
                    ext or "-",
                )

        if not _row_has_user_substance_after_clean(row.get("content"), row.get("entity_detail") if isinstance(row.get("entity_detail"), dict) else None):
            logger.warning(
                "RAG 사용자 응답용 row 제외: insufficient_substance external_id=%s effective_score=%s",
                ext or "-",
                eff_sc,
            )
            continue

        out.append(row)

    logger.info("[rag_sanitize] in=%s out=%s min_best_score=%s", len(results or []), len(out), floor)
    return out


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


def _row_entity_kind_for_answer(r: dict[str, Any]) -> str:
    """검색 결과 한 행이 나타내는 엔티티 축(업체 vs 제품)."""

    d = r.get("entity_detail")
    if isinstance(d, dict):
        et = str(d.get("entity_type") or "").strip().lower()
        if et in ("company", "product"):
            return et
    et2 = str(r.get("entity_type") or "").strip().lower()
    if et2 in ("company", "product"):
        return et2
    tn = str(r.get("table_name") or "").lower()
    if "exhibit_item" in tn or "exhibititem" in tn:
        return "product"
    return "company"


def infer_answer_focus(
    *,
    intent: str,
    retrieval_topic: str | None,
    results: list[dict[str, Any]],
) -> str:
    """답변·LLM 컨텍스트를 한 축(업체 또는 제품)으로 맞출 때 사용."""

    rt = (retrieval_topic or "").strip().lower()
    if rt in ("company", "product"):
        return rt
    it = (intent or "").strip().lower()
    if it == "company":
        return "company"
    if it == "product":
        return "product"
    kinds = [_row_entity_kind_for_answer(r) for r in (results or [])]
    products = sum(1 for k in kinds if k == "product")
    companies = sum(1 for k in kinds if k == "company")
    if products and not companies:
        return "product"
    if companies and not products:
        return "company"
    for r in results or []:
        if (r.get("chunk_typ") == "profile") or isinstance(r.get("entity_detail"), dict):
            return _row_entity_kind_for_answer(r)
    return "company"


def filter_results_by_answer_focus(results: list[dict[str, Any]], focus: str) -> list[dict[str, Any]]:
    """의도와 맞는 행만 남긴다(업체 답변에 제품 청크가 섞이지 않게)."""

    f = (focus or "").strip().lower()
    if f not in ("company", "product"):
        return list(results or [])
    filtered = [r for r in (results or []) if _row_entity_kind_for_answer(r) == f]
    return filtered if filtered else list(results or [])


def format_search_results_for_llm_context(
    results: list[dict[str, Any]],
    *,
    intent: str = "general",
    retrieval_topic: str | None = None,
    language: str = "ko",
) -> str:
    """OpenAI 등 답변 생성용 컨텍스트 포맷터.

    정책:
    - raw chunk 나열 대신, 가능하면 entity_detail 기반 구조화 요약을 우선 포함
    - internal id/metadata/컬럼명/점수는 절대 넣지 않는다.
    - 한 응답에는 업체 또는 제품 중 한 축만 담는다(의도·검색축·결과 다수결이 일치하도록 필터).
    """
    focus = infer_answer_focus(intent=intent, retrieval_topic=retrieval_topic, results=results)
    scoped = filter_results_by_answer_focus(results, focus)
    profiles, evidence = split_search_results_profile_evidence(scoped)
    blocks: list[str] = []
    lang = (language or "ko").strip().lower()
    _is_en = lang == "en"

    if profiles:
        if lang == "en":
            kind_en = "Exhibitor" if focus == "company" else "Product"
            blocks.append(f"【Entity summary】 ({kind_en} core fields)")
        else:
            kind_ko = "업체" if focus == "company" else "제품"
            blocks.append(f"【엔티티 요약】 ({kind_ko} 핵심 정보)")
        for r in profiles:
            d = r.get("entity_detail") if isinstance(r.get("entity_detail"), dict) else None
            if d:
                if d.get("entity_type") == "company":
                    intro = (d.get("description") or d.get("one_liner") or "").strip()
                    cn = (d.get("company_name") or "").strip()
                    hdr = f"— {cn}" if cn else ("— Exhibitor" if _is_en else "— 참가 업체")
                    loc = " ".join(
                        [x for x in [(d.get("hall") or "").strip(), (d.get("booth") or "").strip()] if x]
                    )
                    cat = (d.get("category") or "").strip()
                    addr = (d.get("address") or "").strip()
                    contact = (d.get("contact") or "").strip()
                    web = (d.get("website") or "").strip()
                    majors = d.get("major_products")
                    mp = ""
                    if isinstance(majors, list):
                        mp = ", ".join(str(x).strip() for x in majors if str(x).strip())
                    sec: list[str] = [hdr]
                    if intro:
                        sec.append(("Company overview:" if _is_en else "업체 소개:") + "\n" + intro)
                    bits: list[str] = []
                    if loc:
                        bits.append(f"Location: {loc}" if _is_en else f"위치: {loc}")
                    if cat:
                        bits.append(f"Category: {cat}" if _is_en else f"카테고리: {cat}")
                    if addr:
                        bits.append(f"Address: {addr}" if _is_en else f"주소: {addr}")
                    if contact:
                        bits.append(f"Contact: {contact}" if _is_en else f"연락처: {contact}")
                    if web:
                        bits.append(f"Website: {web}" if _is_en else f"웹사이트: {web}")
                    if mp:
                        bits.append(f"Key products/services: {mp}" if _is_en else f"주요 제품/서비스: {mp}")
                    if bits:
                        sec.append("\n".join(f"· {b}" for b in bits))
                    blocks.append("\n".join(sec))
                else:
                    intro = (d.get("description") or d.get("one_liner") or "").strip()
                    pn = (d.get("product_name") or "").strip()
                    hdr = f"— {pn}" if pn else ("— Exhibit item" if _is_en else "— 전시 품목")
                    manu = (d.get("manufacturer") or "").strip()
                    model = (d.get("model_name") or "").strip()
                    cat = (d.get("category") or "").strip()
                    loc = (d.get("location") or "").strip()
                    sec2: list[str] = [hdr]
                    if intro:
                        sec2.append(("Product overview:" if _is_en else "제품 소개:") + "\n" + intro)
                    bits2: list[str] = []
                    if manu:
                        bits2.append(f"Manufacturer: {manu}" if _is_en else f"제조사: {manu}")
                    if model:
                        bits2.append(f"Model: {model}" if _is_en else f"모델: {model}")
                    if cat:
                        bits2.append(f"Category: {cat}" if _is_en else f"카테고리: {cat}")
                    if loc:
                        bits2.append(f"Show location: {loc}" if _is_en else f"전시 위치: {loc}")
                    if bits2:
                        sec2.append("\n".join(f"· {b}" for b in bits2))
                    blocks.append("\n".join(sec2))
            else:
                body = (r.get("content") or "").strip()
                if len(body) > 600:
                    body = body[:600].rstrip() + "…"
                if body:
                    blocks.append(
                        (f"— Details\n{body}") if _is_en else (f"— 안내 내용\n{body}")
                    )

    if evidence:
        blocks.append(
            "\n【Related excerpts】"
            if _is_en
            else "\n【관련 세부 문구】"
        )
        for r in evidence:
            c = (r.get("content") or "").strip().replace("\n", " ")
            if not c:
                continue
            if len(c) > 300:
                c = c[:300].rstrip() + "…"
            blocks.append(f"· {c}")

    out = "\n".join(blocks).strip()
    return out or ("(Search context is empty.)" if _is_en else "(검색 결과 본문이 비어 있습니다.)")


def build_korean_search_answer(
    query: str,
    results: list[dict[str, Any]],
    *,
    intent: str = "general",
    retrieval_topic: str | None = None,
    language: str = "ko",
) -> str:
    """템플릿 모드에서도 “구조화된 카드형 설명”이 나오도록 답변을 생성한다.

    정책:
    - internal id/메타/컬럼명/점수/원시 JSON 노출 금지
    - entity_detail이 있으면 그것을 우선 사용해 회사/제품 형식을 고정한다.
    """
    q = (query or "").strip()
    lang = (language or "ko").strip().lower()
    _en = lang == "en"
    if not results:
        return (
            f"No matching information for 「{q}」. Try different keywords."
            if _en
            else f"「{q}」에 맞는 정보를 찾지 못했습니다. 다른 표현으로 검색해 보시겠어요?"
        )

    focus = infer_answer_focus(intent=intent, retrieval_topic=retrieval_topic, results=results)
    scoped = filter_results_by_answer_focus(results, focus)
    profiles, evidence = split_search_results_profile_evidence(scoped)
    # 1) entity_detail 우선 (검색축과 같은 entity_type을 우선 선택)
    best_detail = None
    for r in profiles:
        d = r.get("entity_detail")
        if isinstance(d, dict) and str(d.get("entity_type") or "").strip().lower() == focus:
            best_detail = d
            break
    if best_detail is None:
        for r in profiles:
            d = r.get("entity_detail")
            if isinstance(d, dict) and d.get("entity_type"):
                best_detail = d
                break

    if isinstance(best_detail, dict):
        if best_detail.get("entity_type") == "company":
            name = (best_detail.get("company_name") or "").strip() or ("Exhibitor" if _en else "참가 업체")
            hall = (best_detail.get("hall") or "").strip()
            booth = (best_detail.get("booth") or "").strip()
            location = " ".join([x for x in [hall, booth] if x]).strip()
            cat = (best_detail.get("category") or "").strip()
            contact = (best_detail.get("contact") or "").strip()
            web = (best_detail.get("website") or "").strip()
            addr = (best_detail.get("address") or "").strip()
            desc = (best_detail.get("description") or best_detail.get("one_liner") or "").strip()
            majors = best_detail.get("major_products") if isinstance(best_detail.get("major_products"), list) else []
            majors_txt = ", ".join([str(m).strip() for m in majors if str(m).strip()])[:160]
            lines = [name]
            if desc:
                lines.extend(["", "[Company overview]" if _en else "[업체 소개]", desc])
            bullets: list[str] = []
            if location:
                bullets.append(f"· Location: {location}" if _en else f"· 위치: {location}")
            if cat:
                bullets.append(f"· Category: {cat}" if _en else f"· 카테고리: {cat}")
            if addr:
                bullets.append(f"· Address: {addr}" if _en else f"· 주소: {addr}")
            if contact:
                bullets.append(f"· Contact: {contact}" if _en else f"· 연락처: {contact}")
            if web:
                bullets.append(f"· Website: {web}" if _en else f"· 웹사이트: {web}")
            if majors_txt:
                bullets.append(f"· Key products/services: {majors_txt}" if _en else f"· 주요 제품/서비스: {majors_txt}")
            if bullets:
                lines.append("")
                lines.extend(bullets)
            return "\n".join(lines).rstrip()

        # product
        name = (best_detail.get("product_name") or "").strip() or ("Exhibit item" if _en else "전시 품목")
        desc = (best_detail.get("description") or best_detail.get("one_liner") or "").strip()
        manu = (best_detail.get("manufacturer") or "").strip()
        model = (best_detail.get("model_name") or "").strip()
        cat = (best_detail.get("category") or "").strip()
        loc = (best_detail.get("location") or "").strip()
        cont = (best_detail.get("contact") or "").strip()
        webp = (best_detail.get("website") or "").strip()
        lines = [name]
        if desc:
            lines.extend(["", "[Product overview]" if _en else "[제품 소개]", desc])
        bullets = []
        if manu:
            bullets.append(f"· Manufacturer: {manu}" if _en else f"· 제조사: {manu}")
        if model:
            bullets.append(f"· Model: {model}" if _en else f"· 모델: {model}")
        if cat:
            bullets.append(f"· Category: {cat}" if _en else f"· 카테고리: {cat}")
        if loc:
            bullets.append(f"· Show location: {loc}" if _en else f"· 전시 위치: {loc}")
        if cont:
            bullets.append(f"· Contact: {cont}" if _en else f"· 문의: {cont}")
        if webp:
            bullets.append(f"· Website: {webp}" if _en else f"· 웹사이트: {webp}")
        if bullets:
            lines.append("")
            lines.extend(bullets)
        return "\n".join(lines).rstrip()

    # 2) fallback: 기존 요약(하지만 메타는 제거된 상태)
    lines = (
        [f"Here are details that may match your question about 「{q}」.", ""]
        if _en
        else [f"「{q}」와 관련해 안내할 수 있는 내용을 아래에 정리했습니다.", ""]
    )

    if profiles:
        lines.append("■ Overview" if _en else "■ 개요")
        for r in profiles:
            body = (r.get("content") or "").strip()
            if not body:
                continue
            for part in body.split("\n"):
                part = part.strip()
                if part:
                    lines.append(f"    {part}")
        lines.append("")

    if evidence:
        lines.append("■ Related excerpts" if _en else "■ 관련 세부 문구")
        for r in evidence[:6]:
            c = (r.get("content") or "").strip().replace("\n", " ")
            if not c:
                continue
            if len(c) > 200:
                c = c[:200].rstrip() + "…"
            lines.append(f"  · {c}")
        lines.append("")

    lines.append(
        "Need a different name or keyword? Try again with a more specific exhibitor or product."
        if _en
        else "다른 업체명·제품명으로 검색해 보시면 더 잘 맞는 안내를 드릴 수 있어요."
    )
    if not profiles and not evidence:
        return (
            f"No searchable body text for 「{q}」."
            if _en
            else f"「{q}」에 대해 표시할 검색 본문이 없습니다."
        )
    return "\n".join(lines).rstrip()


# 구버전 import/호출자 호환용 별칭 (동일 함수를 가리킴).
_koba_bundle_for_model = _kprint_bundle_for_model
_koba_table_set_for_entity = _kprint_table_set_for_entity
_koba_parent_sql_table = _kprint_parent_sql_table
_fetch_koba_exhibitor_rows = _fetch_kprint_exhibitor_rows
_fetch_koba_exhibit_item_rows = _fetch_kprint_exhibit_item_rows
