"""검색 결과 → 챗봇용 제안 카드(이미지·이름·요약·이어질문 프롬프트)."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import text


def infer_entity_kind_from_table(table_name: str) -> str:
    t = (table_name or "").lower()
    if "exhibit_item" in t or "exhibititem" in t:
        return "exhibit_item"
    if "exhibitor" in t:
        return "exhibitor"
    return "exhibitor"


def _locale_en(language: str | None) -> bool:
    return (language or "").strip().lower() == "en"


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


def _pick_first(kv: dict[str, str], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = (kv.get(k) or "").strip()
        if v:
            return v
    return ""


def build_profile_items_for_card(
    *, kv: dict[str, str], entity_kind: str, language: str = "ko"
) -> list[dict[str, str]]:
    """카드에 표시할 프로필 항목(라벨/값) 구성.

    정책:
    - internal id/key/external_id 등 식별자는 절대 노출하지 않는다.
    - 기업/제품별 우선순위를 다르게 적용한다.
    - language=en 이면 *_eng 컬럼을 우선하고 라벨을 영어로 표시한다.
    - 너무 길어지지 않게 상위 N개만 반환한다.
    """

    kind = (entity_kind or "").strip()
    en = _locale_en(language)

    def add(label: str, value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        items.append({"label": label, "value": v[:160]})

    items: list[dict[str, str]] = []

    if kind == "exhibit_item":
        if en:
            add("Manufacturer", _pick_first(kv, ("manufacturer_eng", "manufacturer_kor", "company_name_eng", "company_name_kor")))
            add("Model", _pick_first(kv, ("model_name", "model", "model_number")))
            add(
                "Category",
                _pick_first(
                    kv,
                    (
                        "item_main_category_label_eng",
                        "item_main_category_label_kor",
                        "item_main_category_label",
                        "exhibition_category_label",
                    ),
                ),
            )
            add("Booth", _pick_first(kv, ("booth_number",)))
            add("Hall", _pick_first(kv, ("exhibit_hall_label_eng", "exhibit_hall_label_kor", "exhibit_hall_label")))
            add("Company", _pick_first(kv, ("company_name_eng", "company_name_kor")))
            add("Website", _pick_first(kv, ("homepage", "website", "company_homepage")))
            add("Phone", _pick_first(kv, ("company_tel", "company_phone", "tel", "phone")))
            add("Email", _pick_first(kv, ("company_email", "email")))
        else:
            add("제조사", _pick_first(kv, ("manufacturer_kor", "manufacturer_eng", "company_name_kor", "company_name_eng")))
            add("모델", _pick_first(kv, ("model_name", "model", "model_number")))
            add(
                "카테고리",
                _pick_first(
                    kv,
                    (
                        "item_main_category_label_kor",
                        "item_main_category_label_eng",
                        "item_main_category_label",
                        "exhibition_category_label",
                    ),
                ),
            )
            add("부스", _pick_first(kv, ("booth_number",)))
            add("전시장", _pick_first(kv, ("exhibit_hall_label_kor", "exhibit_hall_label_eng", "exhibit_hall_label")))
            add("업체", _pick_first(kv, ("company_name_kor", "company_name_eng")))
            add("홈페이지", _pick_first(kv, ("homepage", "website", "company_homepage")))
            add("전화", _pick_first(kv, ("company_tel", "company_phone", "tel", "phone")))
            add("이메일", _pick_first(kv, ("company_email", "email")))
    else:
        if en:
            add("Booth", _pick_first(kv, ("booth_number",)))
            add("Hall", _pick_first(kv, ("exhibit_hall_label_eng", "exhibit_hall_label_kor", "exhibit_hall_label")))
            add(
                "Category",
                _pick_first(
                    kv,
                    (
                        "exhibition_category_label",
                        "item_main_category_label_eng",
                        "item_main_category_label_kor",
                    ),
                ),
            )
            add("Phone", _pick_first(kv, ("company_tel", "company_phone", "tel", "phone")))
            add("Email", _pick_first(kv, ("company_email", "email")))
            add("Website", _pick_first(kv, ("homepage", "website", "company_homepage")))
            add(
                "Address",
                _pick_first(kv, ("company_address_eng", "company_address_kor", "company_addr", "address", "company_address")),
            )
        else:
            add("부스", _pick_first(kv, ("booth_number",)))
            add("홀", _pick_first(kv, ("exhibit_hall_label_kor", "exhibit_hall_label_eng", "exhibit_hall_label")))
            add(
                "분야",
                _pick_first(
                    kv,
                    (
                        "exhibition_category_label",
                        "exhibition_category_label_kor",
                        "item_main_category_label_kor",
                        "item_main_category_label_eng",
                    ),
                ),
            )
            add("전화", _pick_first(kv, ("company_tel", "company_phone", "tel", "phone")))
            add("이메일", _pick_first(kv, ("company_email", "email")))
            add("홈페이지", _pick_first(kv, ("homepage", "website", "company_homepage")))
            add("주소", _pick_first(kv, ("company_address_kor", "company_address_eng", "company_addr", "address", "company_address")))

    # label 중복 제거(순서 유지)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for it in items:
        lab = str(it.get("label") or "")
        if not lab or lab in seen:
            continue
        seen.add(lab)
        out.append(it)
    return out[:8]


def collect_suggestion_seeds(
    results: list[dict[str, Any]], *, max_cards: int = 8, language: str = "ko"
) -> list[dict[str, Any]]:
    """RRF 순서대로 profile 행 우선, external_id 단위로 최대 ``max_cards``개."""
    seen: set[tuple[str, str]] = set()
    seeds: list[dict[str, Any]] = []
    en = _locale_en(language)

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
        if en:
            title = (
                kv.get("company_name_eng")
                or kv.get("company_name_kor")
                or kv.get("product_name_eng")
                or kv.get("product_name_kor")
                or ext
            )
            bit_keys = (
                "booth_number",
                "exhibition_category_label",
                "exhibit_hall_label_eng",
                "exhibit_hall_label_kor",
                "item_main_category_label_eng",
                "item_main_category_label_kor",
                "model_name",
                "manufacturer_eng",
                "manufacturer_kor",
            )
        else:
            title = (
                kv.get("company_name_kor")
                or kv.get("company_name_eng")
                or kv.get("product_name_kor")
                or kv.get("product_name_eng")
                or ext
            )
            bit_keys = (
                "booth_number",
                "exhibition_category_label",
                "exhibit_hall_label_kor",
                "exhibit_hall_label_eng",
                "item_main_category_label_kor",
                "item_main_category_label_eng",
                "model_name",
                "manufacturer_kor",
                "manufacturer_eng",
            )
        bits: list[str] = []
        for lab in bit_keys:
            if kv.get(lab):
                bits.append(kv[lab])

        profile_items = build_profile_items_for_card(kv=kv, entity_kind=kind, language=language)
        seeds.append(
            {
                "external_id": ext,
                "entity_kind": kind,
                "title": title[:200],
                "subtitle": " · ".join(bits)[:280],
                "profile_items": profile_items,
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


def hydrate_suggestion_cards_sync(seeds: list[dict[str, Any]], *, language: str = "ko") -> list[dict[str, Any]]:
    """동기 엔진 + 순수 SQL로만 행 로드한다(ORM 세션 없음 → async/greenlet 경로 차단)."""

    from app.rag.pipeline import engine as rag_engine

    en = _locale_en(language)
    item_sql = text(
        """
        SELECT product_image_link, product_name_kor, product_name_eng,
               company_name_kor, company_name_eng,
               item_main_category_label_kor, item_main_category_label_eng,
               model_name, exhibit_hall_label_kor, exhibit_hall_label_eng
          FROM kprint_exhibit_item
         WHERE external_id = :ext
         LIMIT 1
        """
    )
    exhib_sql = text(
        """
        SELECT company_logo_link, company_name_kor, company_name_eng,
               exhibition_category_label, booth_number,
               exhibit_hall_label_kor, exhibit_hall_label_eng
          FROM kprint_exhibitor
         WHERE external_id = :ext
         LIMIT 1
        """
    )

    out: list[dict[str, Any]] = []
    with rag_engine.connect() as conn:
        for s in seeds:
            ext = str(s.get("external_id") or "").strip()
            kind = str(s.get("entity_kind") or "exhibitor")
            title = (s.get("title") or ext)[:200]
            subtitle = (s.get("subtitle") or "")[:280]
            profile_items: list[Any] = s.get("profile_items") if isinstance(s.get("profile_items"), list) else []
            image_url: str | None = None
            if kind == "exhibit_item":
                r = conn.execute(item_sql, {"ext": ext})
                row = r.mappings().first()
                if row:
                    pil = row.get("product_image_link") or ""
                    image_url = str(pil).strip() or None
                    rd = dict(row)
                    kv = {str(k): str(v).strip() for k, v in rd.items() if v is not None and str(v).strip()}
                    profile_items = build_profile_items_for_card(kv=kv, entity_kind=kind, language=language)
                    if en:
                        pn = row.get("product_name_eng") or row.get("product_name_kor") or title
                        bits = [
                            x
                            for x in (
                                row.get("company_name_eng"),
                                row.get("company_name_kor"),
                                row.get("item_main_category_label_eng"),
                                row.get("item_main_category_label_kor"),
                                row.get("model_name"),
                            )
                            if x
                        ]
                    else:
                        pn = row.get("product_name_kor") or row.get("product_name_eng") or title
                        bits = [
                            x
                            for x in (
                                row.get("company_name_kor"),
                                row.get("company_name_eng"),
                                row.get("item_main_category_label_kor"),
                                row.get("item_main_category_label_eng"),
                                row.get("model_name"),
                            )
                            if x
                        ]
                    title = str(pn)[:200]
                    subtitle = (subtitle or " · ".join(str(b) for b in bits))[:280]
            else:
                r = conn.execute(exhib_sql, {"ext": ext})
                row = r.mappings().first()
                if row:
                    cl = row.get("company_logo_link") or ""
                    image_url = str(cl).strip() or None
                    rd = dict(row)
                    kv = {str(k): str(v).strip() for k, v in rd.items() if v is not None and str(v).strip()}
                    profile_items = build_profile_items_for_card(kv=kv, entity_kind=kind, language=language)
                    if en:
                        cn = row.get("company_name_eng") or row.get("company_name_kor") or title
                        bits = [
                            x
                            for x in (
                                row.get("exhibition_category_label"),
                                row.get("booth_number"),
                                row.get("exhibit_hall_label_eng"),
                                row.get("exhibit_hall_label_kor"),
                            )
                            if x
                        ]
                    else:
                        cn = row.get("company_name_kor") or row.get("company_name_eng") or title
                        bits = [
                            x
                            for x in (
                                row.get("exhibition_category_label"),
                                row.get("booth_number"),
                                row.get("exhibit_hall_label_kor"),
                                row.get("exhibit_hall_label_eng"),
                            )
                            if x
                        ]
                    title = str(cn)[:200]
                    subtitle = (subtitle or " · ".join(str(b) for b in bits))[:280]

            if kind == "exhibit_item":
                follow = (
                    f"Tell me about {title} (external_id: {ext})"
                    if en
                    else f"{title}에 대한 정보를 알려줘 (external_id: {ext})"
                )
            else:
                follow = (
                    f"Tell me about {title} (external_id: {ext})"
                    if en
                    else f"{title}에 대한 정보를 알려줘 (external_id: {ext})"
                )
            out.append(
                {
                    "external_id": ext,
                    "entity_kind": kind,
                    "title": title,
                    "subtitle": subtitle,
                    "image_url": image_url,
                    "follow_prompt": follow[:500],
                    "profile_items": profile_items,
                }
            )
    return out


async def hydrate_suggestion_cards(seeds: list[dict[str, Any]], *, language: str = "ko") -> list[dict[str, Any]]:
    """AsyncSession 대신 동기 세션을 워커 스레드에서 실행한다."""
    if not seeds:
        return []
    return await asyncio.to_thread(hydrate_suggestion_cards_sync, seeds, language=language)


async def build_retrieval_suggestion_cards(
    results: list[dict[str, Any]], *, language: str = "ko"
) -> list[dict[str, Any]]:
    seeds = collect_suggestion_seeds(results, max_cards=8, language=language)
    return await hydrate_suggestion_cards(seeds, language=language)
