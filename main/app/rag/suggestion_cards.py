"""검색 결과 → 챗봇용 제안 카드(이미지·이름·요약·이어질문 프롬프트)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.kprint.models import KprintExhibitItem, KprintExhibitor


def infer_entity_kind_from_table(table_name: str) -> str:
    t = (table_name or "").lower()
    if "exhibit_item" in t or "exhibititem" in t:
        return "exhibit_item"
    if "exhibitor" in t:
        return "exhibitor"
    return "exhibitor"


def parse_profile_kv_lines(content: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in (content or "").splitlines():
        if ":" not in raw:
            continue
        k, v = raw.split(":", 1)
        key = k.strip()
        if key:
            out[key] = v.strip()
    return out


def collect_suggestion_seeds(results: list[dict[str, Any]], *, max_cards: int = 8) -> list[dict[str, Any]]:
    """RRF 순서대로 profile 행 우선, external_id 단위로 최대 ``max_cards``개."""
    seen: set[tuple[str, str]] = set()
    seeds: list[dict[str, Any]] = []

    def push_from_row(r: dict[str, Any]) -> None:
        ext = str(r.get("external_id") or "").strip()
        if not ext:
            return
        tn = str(r.get("table_name") or "")
        kind = infer_entity_kind_from_table(tn)
        key = (kind, ext)
        if key in seen:
            return
        seen.add(key)
        kv = parse_profile_kv_lines(str(r.get("content") or ""))
        title = (
            kv.get("company_name_kor")
            or kv.get("company_name_eng")
            or kv.get("product_name_kor")
            or kv.get("product_name_eng")
            or ext
        )
        bits: list[str] = []
        for lab in (
            "booth_number",
            "exhibition_category_label",
            "exhibit_hall_label_kor",
            "item_main_category_label_kor",
            "model_name",
            "manufacturer_kor",
        ):
            if kv.get(lab):
                bits.append(kv[lab])
        seeds.append(
            {
                "external_id": ext,
                "entity_kind": kind,
                "title": title[:200],
                "subtitle": " · ".join(bits)[:280],
            }
        )

    for r in results:
        if r.get("chunk_typ") != "profile":
            continue
        push_from_row(r)
        if len(seeds) >= max_cards:
            return seeds

    for r in results:
        if r.get("chunk_typ") == "profile":
            continue
        push_from_row(r)
        if len(seeds) >= max_cards:
            break

    return seeds


async def hydrate_suggestion_cards(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """DB에서 로고·제품 이미지·표시명을 보강한다."""
    if not seeds:
        return []
    out: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as session:
        for s in seeds:
            ext = str(s.get("external_id") or "").strip()
            kind = str(s.get("entity_kind") or "exhibitor")
            title = (s.get("title") or ext)[:200]
            subtitle = (s.get("subtitle") or "")[:280]
            image_url: str | None = None
            if kind == "exhibit_item":
                row = await session.scalar(select(KprintExhibitItem).where(KprintExhibitItem.external_id == ext))
                if row:
                    image_url = (row.product_image_link or "").strip() or None
                    title = (row.product_name_kor or row.product_name_eng or title)[:200]
                    bits = [
                        x
                        for x in (
                            row.company_name_kor,
                            row.item_main_category_label_kor,
                            row.model_name,
                        )
                        if x
                    ]
                    subtitle = (subtitle or " · ".join(bits))[:280]
            else:
                row = await session.scalar(select(KprintExhibitor).where(KprintExhibitor.external_id == ext))
                if row:
                    image_url = (row.company_logo_link or "").strip() or None
                    title = (row.company_name_kor or row.company_name_eng or title)[:200]
                    bits = [
                        x
                        for x in (
                            row.exhibition_category_label,
                            row.booth_number,
                            row.exhibit_hall_label_kor,
                        )
                        if x
                    ]
                    subtitle = (subtitle or " · ".join(bits))[:280]

            follow = f"{title} (external_id: {ext})에 대해 부스·제품·연락처 위주로 자세히 알려줘"
            out.append(
                {
                    "external_id": ext,
                    "entity_kind": kind,
                    "title": title,
                    "subtitle": subtitle,
                    "image_url": image_url,
                    "follow_prompt": follow[:500],
                }
            )
    return out


async def build_retrieval_suggestion_cards(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seeds = collect_suggestion_seeds(results, max_cards=8)
    return await hydrate_suggestion_cards(seeds)
