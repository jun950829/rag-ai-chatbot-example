"""pgvector 임베딩 테이블 검색 (원 프로젝트의 UNION + `<=>` 거리 검색을 포팅)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

import sqlalchemy as sa
from sqlalchemy import create_engine

from app.core.config import get_settings


def _to_sync_dsn(dsn: str) -> str:
    # new_main/.env.example은 asyncpg DSN을 쓰므로 sync용으로 변환
    d = (dsn or "").strip()
    if d.startswith("postgresql+asyncpg://"):
        return d.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if d.startswith("postgresql://"):
        return d.replace("postgresql://", "postgresql+psycopg://", 1)
    return d


_engine = None


def get_sync_engine():
    global _engine
    if _engine is not None:
        return _engine
    st = get_settings()
    dsn = _to_sync_dsn(st.postgres_dsn)
    if not dsn:
        raise RuntimeError("POSTGRES_DSN is not set")
    _engine = create_engine(dsn, future=True, pool_pre_ping=True)
    return _engine


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in vec) + "]"


@dataclass(frozen=True)
class KprintTableSet:
    profile_kor: str
    profile_eng: str
    evidence_kor: str
    evidence_eng: str


@dataclass(frozen=True)
class KprintModelTableBundle:
    exhibitor: KprintTableSet
    exhibit_item: KprintTableSet


_QWEN3_0_6B = KprintModelTableBundle(
    exhibitor=KprintTableSet(
        profile_kor="kprint_exhibitor_profile_embedding_qwen3_0_6b_kor",
        profile_eng="kprint_exhibitor_profile_embedding_qwen3_0_6b_eng",
        evidence_kor="kprint_exhibitor_evidence_embedding_qwen3_0_6b_kor",
        evidence_eng="kprint_exhibitor_evidence_embedding_qwen3_0_6b_eng",
    ),
    exhibit_item=KprintTableSet(
        profile_kor="kprint_exhibit_item_profile_embedding_qwen3_0_6b_kor",
        profile_eng="kprint_exhibit_item_profile_embedding_qwen3_0_6b_eng",
        evidence_kor="kprint_exhibit_item_evidence_embedding_qwen3_0_6b_kor",
        evidence_eng="kprint_exhibit_item_evidence_embedding_qwen3_0_6b_eng",
    ),
)


def kprint_bundle_for_model(model_id: str) -> KprintModelTableBundle:
    # 현재 운영 번들만 지원 (원 프로젝트도 model_id로 분기하지만 기본은 qwen3 0.6b)
    _ = (model_id or "").strip()
    return _QWEN3_0_6B


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
    top_k = max(1, int(top_k))
    bundle = kprint_bundle_for_model(model_id)

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

    all_specs: list[tuple[str, str, str]] = []
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

    if per_table_limit is None:
        per_table_limit = min(max(top_k * 5, 14), 36)
    else:
        per_table_limit = max(1, int(per_table_limit))

    union_parts: list[str] = []
    for table_name, typ, _table_lang in selected:
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

    params = {"embedding": _vector_literal(query_embedding), "per_table_limit": per_table_limit, "top_k": top_k}
    engine = get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(sa.text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def fetch_entity_chunks_text_by_external_id(
    external_id: str,
    model_id: str,
    entity_kind: str | None = None,
    *,
    max_chars: int = 48_000,
) -> str:
    """카드의 ``external_id`` 로 임베딩 테이블에서 본문만 모은다 (LLM 컨텍스트용)."""
    ext = (external_id or "").strip()
    if not ext:
        return ""
    bundle = kprint_bundle_for_model(model_id)
    kind = (entity_kind or "").strip().lower()
    if kind == "exhibit_item":
        table_sets: tuple[KprintTableSet, ...] = (bundle.exhibit_item,)
    elif kind in ("exhibitor", "company_query", "company"):
        table_sets = (bundle.exhibitor,)
    else:
        table_sets = (bundle.exhibitor, bundle.exhibit_item)

    blocks: list[str] = []
    sep = "\n\n---\n\n"
    engine = get_sync_engine()
    with engine.connect() as conn:
        for ts in table_sets:
            for table_name, typ_label in (
                (ts.profile_kor, "profile_kor"),
                (ts.profile_eng, "profile_eng"),
                (ts.evidence_kor, "evidence_kor"),
                (ts.evidence_eng, "evidence_eng"),
            ):
                sql = sa.text(
                    f"""
                    SELECT source_field, chunk_index, lang, content
                    FROM {table_name}
                    WHERE external_id = :eid
                      AND content IS NOT NULL
                      AND btrim(content) <> ''
                    ORDER BY source_field NULLS LAST, chunk_index NULLS LAST
                    """
                )
                rows = conn.execute(sql, {"eid": ext}).mappings().all()
                for r in rows:
                    sf = str(r.get("source_field") or "")
                    ci = r.get("chunk_index")
                    lang = str(r.get("lang") or "")
                    body = str(r.get("content") or "").strip()
                    if not body:
                        continue
                    head = f"[{typ_label}] {sf} idx={ci} lang={lang}".strip()
                    blocks.append(f"{head}\n{body}")
                    joined = sep.join(blocks)
                    if len(joined) >= max_chars:
                        return joined[:max_chars].rstrip() + "\n…(truncated)"
    return sep.join(blocks)[:max_chars]


# ---------------------------------------------------------------------------
# 카탈로그 테이블 조회 (구조화 필드: 제조사, 이미지, 전시장 등)
# ---------------------------------------------------------------------------

_EXHIBIT_ITEM_CATALOG_COLS = (
    "external_id",
    "product_name_kor", "product_name_eng",
    "model_name",
    "manufacturer_kor", "manufacturer_eng",
    "item_main_category_label_kor", "item_main_category_label_eng",
    "item_sub_category_label_kor", "item_sub_category_label_eng",
    "exhibition_category_label",
    "exhibit_hall_label_kor", "exhibit_hall_label_eng",
    "exhibit_status_label_kor", "exhibit_status_label_eng",
    "exhibit_year",
    "country_of_origin_label_kor", "country_of_origin_label_eng",
    "company_name_kor", "company_name_eng",
    "product_image_link",
    "product_description_kor", "product_description_eng",
    "certification_status_kor", "certification_status_eng",
)

_EXHIBITOR_CATALOG_COLS = (
    "external_id",
    "company_name_kor", "company_name_eng",
    "exhibition_category_label",
    "booth_number",
    "homepage",
    "country_label_kor", "country_label_eng",
    "exhibit_hall_label_kor", "exhibit_hall_label_eng",
    "exhibit_status_label_kor", "exhibit_status_label_eng",
    "exhibit_year",
    "company_address_kor", "company_address_eng",
    "exhibition_manager_tel",
    "company_description_kor", "company_description_eng",
    "company_logo_link",
    "item_main_category_label_kor_list",
    "item_sub_category_label_kor_list",
)


def fetch_catalog_rows_by_external_ids(
    external_ids: list[str],
    entity_kind: str,
) -> dict[str, dict[str, Any]]:
    """카탈로그 테이블에서 구조화 필드를 ``external_id`` 로 일괄 조회한다."""
    eids = [e.strip() for e in (external_ids or []) if (e or "").strip()]
    if not eids:
        return {}
    kind = (entity_kind or "").strip().lower()
    if kind == "exhibit_item":
        table = "kprint_exhibit_item"
        cols = _EXHIBIT_ITEM_CATALOG_COLS
    else:
        table = "kprint_exhibitor"
        cols = _EXHIBITOR_CATALOG_COLS
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":e{i}" for i in range(len(eids)))
    sql = sa.text(f"SELECT {col_list} FROM {table} WHERE external_id IN ({placeholders})")
    params = {f"e{i}": eid for i, eid in enumerate(eids)}
    engine = get_sync_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        eid = str(r.get("external_id") or "").strip()
        if eid:
            out[eid] = {k: r.get(k) for k in cols}
    return out


def lookup_exhibitor_homepage_by_company_name(company_names: list[str]) -> dict[str, str]:
    """회사명 리스트로 kprint_exhibitor 에서 homepage URL을 일괄 조회한다."""
    names = [n.strip() for n in (company_names or []) if (n or "").strip()]
    if not names:
        return {}
    placeholders = ", ".join(f":n{i}" for i in range(len(names)))
    sql = sa.text(
        f"SELECT company_name_kor, company_name_eng, homepage "
        f"FROM kprint_exhibitor "
        f"WHERE (company_name_kor IN ({placeholders}) OR company_name_eng IN ({placeholders})) "
        f"AND homepage IS NOT NULL AND btrim(homepage) <> ''"
    )
    params = {f"n{i}": n for i, n in enumerate(names)}
    engine = get_sync_engine()
    result: dict[str, str] = {}
    with engine.connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    for r in rows:
        hp = str(r.get("homepage") or "").strip()
        if not hp:
            continue
        for key in ("company_name_kor", "company_name_eng"):
            name = str(r.get(key) or "").strip()
            if name:
                result[name] = hp
    return result


def format_catalog_as_context(catalog: dict[str, Any], *, language: str = "ko") -> str:
    """카탈로그 dict → LLM 컨텍스트용 라벨: 값 텍스트 블록."""
    lang = (language or "ko").strip().lower()
    _SKIP_FIELDS = {"external_id", "product_image_link", "company_logo_link", "_resolved_homepage"}
    lines: list[str] = []
    for k, v in catalog.items():
        if k in _SKIP_FIELDS:
            continue
        raw = v
        if isinstance(raw, list):
            raw = ", ".join(str(x) for x in raw if x)
        val = str(raw or "").strip()
        if not val:
            continue
        if lang == "en" and k.endswith("_kor"):
            alt = k[:-4] + "_eng"
            if (catalog.get(alt) or ""):
                continue
        if lang == "ko" and k.endswith("_eng"):
            alt = k[:-4] + "_kor"
            if (catalog.get(alt) or ""):
                continue
        label = k.replace("_", " ").title()
        lines.append(f"{label}: {val}")
    # 업체에서 조회된 homepage가 있으면 추가
    resolved_hp = str(catalog.get("_resolved_homepage") or "").strip()
    if resolved_hp:
        label = "Website" if lang == "en" else "웹사이트"
        lines.append(f"{label}: {resolved_hp}")
    return "\n".join(lines)

