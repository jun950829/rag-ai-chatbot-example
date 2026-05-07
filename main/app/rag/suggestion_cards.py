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


def build_profile_items_for_card(*, kv: dict[str, str], entity_kind: str) -> list[dict[str, str]]:
    """카드에 표시할 프로필 항목(라벨/값) 구성.

    정책:
    - internal id/key/external_id 등 식별자는 절대 노출하지 않는다.
    - 기업/제품별 우선순위를 다르게 적용한다.
    - 너무 길어지지 않게 상위 N개만 반환한다.
    """

    kind = (entity_kind or "").strip()

    def add(label: str, value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        items.append({"label": label, "value": v[:160]})

    items: list[dict[str, str]] = []

    if kind == "exhibit_item":
        # 제품: 제조사/모델/카테고리/부스 우선
        add("제조사", _pick_first(kv, ("manufacturer_kor", "manufacturer_eng", "company_name_kor")))
        add("모델", _pick_first(kv, ("model_name", "model", "model_number")))
        add("카테고리", _pick_first(kv, ("item_main_category_label_kor", "item_main_category_label", "exhibition_category_label")))
        add("부스", _pick_first(kv, ("booth_number",)))
        # 추가 노출 가능 정보
        add("전시장", _pick_first(kv, ("exhibit_hall_label_kor", "exhibit_hall_label")))
        add("업체", _pick_first(kv, ("company_name_kor", "company_name_eng")))
        add("홈페이지", _pick_first(kv, ("homepage", "website", "company_homepage")))
        add("전화", _pick_first(kv, ("company_tel", "company_phone", "tel", "phone")))
        add("이메일", _pick_first(kv, ("company_email", "email")))
    else:
        # 기업: 부스/홀/분야/연락처 우선
        add("부스", _pick_first(kv, ("booth_number",)))
        add("홀", _pick_first(kv, ("exhibit_hall_label_kor", "exhibit_hall_label")))
        add("분야", _pick_first(kv, ("exhibition_category_label", "exhibition_category_label_kor", "item_main_category_label_kor")))
        # 연락처는 전화→이메일→홈페이지 순으로 붙인다.
        add("전화", _pick_first(kv, ("company_tel", "company_phone", "tel", "phone")))
        add("이메일", _pick_first(kv, ("company_email", "email")))
        add("홈페이지", _pick_first(kv, ("homepage", "website", "company_homepage")))
        # 추가
        add("주소", _pick_first(kv, ("company_addr", "address", "company_address")))

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

        # UI에 보여줄 프로필 요약(식별자/키 값 노출 금지)
        profile_items = build_profile_items_for_card(kv=kv, entity_kind=kind)
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


def hydrate_suggestion_cards_sync(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """동기 엔진 + 순수 SQL로만 행 로드한다(ORM 세션 없음 → async/greenlet 경로 차단)."""

    from app.rag.pipeline import engine as rag_engine

    item_sql = text(
        """
        SELECT product_image_link, product_name_kor, product_name_eng,
               company_name_kor, item_main_category_label_kor, model_name
          FROM kprint_exhibit_item
         WHERE external_id = :ext
         LIMIT 1
        """
    )
    exhib_sql = text(
        """
        SELECT company_logo_link, company_name_kor, company_name_eng,
               exhibition_category_label, booth_number, exhibit_hall_label_kor
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
            profile_items = s.get("profile_items") if isinstance(s.get("profile_items"), list) else []
            image_url: str | None = None
            if kind == "exhibit_item":
                r = conn.execute(item_sql, {"ext": ext})
                row = r.mappings().first()
                if row:
                    pil = row.get("product_image_link") or ""
                    image_url = str(pil).strip() or None
                    pn = row.get("product_name_kor") or row.get("product_name_eng") or title
                    title = str(pn)[:200]
                    bits = [
                        x
                        for x in (
                            row.get("company_name_kor"),
                            row.get("item_main_category_label_kor"),
                            row.get("model_name"),
                        )
                        if x
                    ]
                    subtitle = (subtitle or " · ".join(str(b) for b in bits))[:280]
            else:
                r = conn.execute(exhib_sql, {"ext": ext})
                row = r.mappings().first()
                if row:
                    cl = row.get("company_logo_link") or ""
                    image_url = str(cl).strip() or None
                    cn = row.get("company_name_kor") or row.get("company_name_eng") or title
                    title = str(cn)[:200]
                    bits = [
                        x
                        for x in (
                            row.get("exhibition_category_label"),
                            row.get("booth_number"),
                            row.get("exhibit_hall_label_kor"),
                        )
                        if x
                    ]
                    subtitle = (subtitle or " · ".join(str(b) for b in bits))[:280]

            # follow_prompt는 화면에는 "회사/제품 정보 알려줘"로 보이되,
            # 내부적으로는 external_id를 함께 전송해 직접 조회가 가능하게 한다.
            if kind == "exhibit_item":
                follow = f"{title}에 대한 정보를 알려줘 (external_id: {ext})"
            else:
                follow = f"{title}에 대한 정보를 알려줘 (external_id: {ext})"
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


async def hydrate_suggestion_cards(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """AsyncSession 대신 동기 세션을 워커 스레드에서 실행한다."""
    if not seeds:
        return []
    return await asyncio.to_thread(hydrate_suggestion_cards_sync, seeds)


async def build_retrieval_suggestion_cards(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seeds = collect_suggestion_seeds(results, max_cards=8)
    return await hydrate_suggestion_cards(seeds)
