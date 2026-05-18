"""7단계: 카드 생성 + 카탈로그 hydrate + 카드 상세 스트리밍."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import get_settings
from app.observability.tracing import trace_stage
from app.prompt.card_detail import build_card_detail_messages
from app.retrieval.vector_db import (
    fetch_catalog_rows_by_external_ids,
    fetch_entity_chunks_text_by_external_id,
    format_catalog_as_context,
    lookup_exhibitor_homepage_by_company_name,
)
from app.services.steps.cache import get_card_detail_cache, save_card_detail_cache
from app.services.steps.llm_stream import stream_llm_answer
from app.services.suggestion_cards import build_cards_from_context_lines, build_cards_from_rows


def _hydrate_cards_with_catalog(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """카드 리스트에 카탈로그 구조화 필드(image_url, subtitle 보강)를 합친다."""
    if not cards:
        return cards
    by_kind: dict[str, list[str]] = {}
    for c in cards:
        ext = (c.get("external_id") or "")
        kind = (c.get("entity_kind") or "exhibitor")
        if ext:
            by_kind.setdefault(kind, []).append(ext)

    catalogs: dict[str, dict[str, Any]] = {}
    for kind, eids in by_kind.items():
        catalogs.update(fetch_catalog_rows_by_external_ids(eids, kind))

    # 제품 카드의 제조사/회사명을 수집하여 업체 homepage 일괄 조회
    company_names_for_items: list[str] = []
    for c in cards:
        ext = (c.get("external_id") or "")
        cat = catalogs.get(ext)
        if not cat or (c.get("entity_kind") or "") != "exhibit_item":
            continue
        for fld in ("company_name_kor", "company_name_eng", "manufacturer_kor", "manufacturer_eng"):
            v = str(cat.get(fld) or "").strip()
            if v and v not in company_names_for_items:
                company_names_for_items.append(v)

    homepage_map: dict[str, str] = {}
    if company_names_for_items:
        homepage_map = lookup_exhibitor_homepage_by_company_name(company_names_for_items)

    for c in cards:
        ext = (c.get("external_id") or "")
        cat = catalogs.get(ext)
        if not cat:
            continue
        kind = (c.get("entity_kind") or "")
        if kind == "exhibit_item":
            if not c.get("image_url"):
                c["image_url"] = (cat.get("product_image_link") or "").strip() or None
            name = (cat.get("product_name_kor") or cat.get("product_name_eng") or "").strip()
            if name and (not c.get("title") or c["title"] == ext):
                c["title"] = name[:200]
            # 제조사/회사명으로 업체 homepage 매핑
            for fld in ("company_name_kor", "company_name_eng", "manufacturer_kor", "manufacturer_eng"):
                comp = str(cat.get(fld) or "").strip()
                if comp and comp in homepage_map:
                    c["website"] = homepage_map[comp]
                    break
        else:
            if not c.get("image_url"):
                c["image_url"] = (cat.get("company_logo_link") or "").strip() or None
            name = (cat.get("company_name_kor") or cat.get("company_name_eng") or "").strip()
            if name and (not c.get("title") or c["title"] == ext):
                c["title"] = name[:200]
            hp = str(cat.get("homepage") or "").strip()
            if hp:
                c["website"] = hp
        parts: list[str] = []
        if kind == "exhibit_item":
            for fld, label in (
                ("manufacturer_kor", "제조사"),
                ("item_main_category_label_kor", "카테고리"),
                ("exhibit_hall_label_kor", "전시장"),
                ("country_of_origin_label_kor", "원산지"),
            ):
                v = str(cat.get(fld) or "").strip()
                if v:
                    parts.append(f"{label}: {v}")
        else:
            for fld, label in (
                ("exhibition_category_label", "전시 분야"),
                ("exhibit_hall_label_kor", "전시장"),
                ("booth_number", "부스"),
                ("country_label_kor", "국가"),
            ):
                v = str(cat.get(fld) or "").strip()
                if v:
                    parts.append(f"{label}: {v}")
        if parts:
            c["subtitle"] = " · ".join(parts)[:220]
    return cards


async def make_cards(
    *,
    rows: list[dict[str, Any]],
    context: str,
    query: str,
    language: str,
) -> tuple[list[dict[str, Any]], str]:
    """검색 행 → 카드 생성 → 카탈로그 hydrate → enriched 컨텍스트 반환."""
    cards = build_cards_from_rows(rows, query=query)
    if not cards and (context or "").strip():
        cards = build_cards_from_context_lines(context, query=query)

    enriched_ctx = context
    if cards:
        async with trace_stage("chat.hydrate_cards"):
            cards = await asyncio.to_thread(_hydrate_cards_with_catalog, cards)
        ext_ids = [c.get("external_id") or "" for c in cards if (c.get("external_id") or "").strip()]
        if ext_ids:
            catalog_blocks: list[str] = []
            for kind_key in ("exhibit_item", "exhibitor"):
                kind_eids = [
                    c.get("external_id") or ""
                    for c in cards
                    if (c.get("entity_kind") or "") == kind_key and (c.get("external_id") or "").strip()
                ]
                if kind_eids:
                    cat_map = await asyncio.to_thread(fetch_catalog_rows_by_external_ids, kind_eids, kind_key)
                    for eid, cat in cat_map.items():
                        block = format_catalog_as_context(cat, language=language)
                        if block:
                            catalog_blocks.append(f"[{eid}]\n{block}")
            if catalog_blocks:
                enriched_ctx = context + "\n\n--- 카탈로그 보충 ---\n" + "\n\n".join(catalog_blocks)

    return cards, enriched_ctx


async def stream_card_detail(
    *, session_id: str, external_id: str, entity_kind: str | None, language: str = "ko"
) -> tuple[list[dict[str, Any]], AsyncIterator[str]]:
    """카드 ``external_id`` 로 DB 본문을 읽은 뒤, LLM만 스트리밍 (새 RAG 검색 없음)."""
    _ = session_id
    ext = (external_id or "").strip()
    lang = (language or "ko").strip().lower()
    if not ext:

        async def _bad() -> AsyncIterator[str]:
            yield ("Identifier is empty." if lang == "en" else "식별자가 비어 있습니다.")

        return [], _bad()

    st = get_settings()
    kind = (entity_kind or "").strip().lower()

    # card detail 캐시 조회
    async with trace_stage("chat.card_detail_cache"):
        cached = await get_card_detail_cache(kind or "exhibitor", ext, lang)
    if cached is not None:
        async def _cached_detail() -> AsyncIterator[str]:
            yield cached
        return [], _cached_detail()

    async def _tokens() -> AsyncIterator[str]:
        chunk_text = await asyncio.to_thread(
            fetch_entity_chunks_text_by_external_id,
            ext,
            st.retrieval_model_id,
            entity_kind,
        )
        cat_map = await asyncio.to_thread(
            fetch_catalog_rows_by_external_ids,
            [ext],
            kind or "exhibitor",
        )
        cat = cat_map.get(ext)

        if cat and kind == "exhibit_item":
            comp_names = [
                str(cat.get(f) or "").strip()
                for f in ("company_name_kor", "company_name_eng", "manufacturer_kor", "manufacturer_eng")
                if str(cat.get(f) or "").strip()
            ]
            if comp_names:
                hp_map = await asyncio.to_thread(lookup_exhibitor_homepage_by_company_name, comp_names)
                for cn in comp_names:
                    if cn in hp_map:
                        cat["_resolved_homepage"] = hp_map[cn]
                        break

        cat_text = format_catalog_as_context(cat, language=lang) if cat else ""

        combined = ""
        if cat_text:
            combined += f"[구조화 필드]\n{cat_text}\n\n"
        if (chunk_text or "").strip():
            combined += f"[임베딩 청크 본문]\n{chunk_text}"
        combined = combined.strip()

        if not combined:
            yield ("No DB content found for this item." if lang == "en" else "요청한 항목의 DB 내용을 찾지 못했습니다.")
            return

        msgs = build_card_detail_messages(evidence=combined, entity_kind=entity_kind, language=lang)
        full_text: dict[str, str] = {"v": ""}
        try:
            async with trace_stage("chat.card_detail_llm"):
                async for piece in stream_llm_answer(messages=msgs):
                    full_text["v"] += piece
                    yield piece
        finally:
            if full_text["v"]:
                await save_card_detail_cache(kind or "exhibitor", ext, lang, full_text["v"])

    return [], _tokens()
