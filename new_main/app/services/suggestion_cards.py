"""검색 행 → 프론트 SuggestionCarousel 용 카드 (main hydrate 없이 최소 필드)."""

from __future__ import annotations

import re
from typing import Any

# DB/임베딩 청크에 흔한 snake_case 키 → 카드·사용자에게 보일 한글 라벨
_FIELD_LABEL_KO: dict[str, str] = {
    "company_name_kor": "회사명",
    "company_name_eng": "회사명(영문)",
    "product_name_kor": "제품명",
    "product_name_eng": "제품명(영문)",
    "model_name": "모델명",
    "manufacturer_kor": "제조사",
    "manufacturer_eng": "제조사(영문)",
    "item_main_category_label_kor": "주요 카테고리",
    "item_main_category_label_eng": "주요 카테고리(영문)",
    "item_sub_category_label_kor": "세부 카테고리",
    "item_sub_category_label_eng": "세부 카테고리(영문)",
    "item_main_category": "주요 카테고리 코드",
    "item_sub_category": "세부 카테고리 코드",
    "exhibition_category_label": "전시 분야",
    "exhibit_hall_label_kor": "전시장",
    "exhibit_hall_label_eng": "전시장(영문)",
    "exhibit_status_label_kor": "부스 상태",
    "exhibit_status_label_eng": "부스 상태(영문)",
    "exhibit_year": "전시 연도",
    "country_of_origin_label_kor": "원산지",
    "country_of_origin_label_eng": "원산지(영문)",
    "country_of_origin": "원산지 코드",
    "country_label_kor": "국가",
    "country_label_eng": "국가(영문)",
    "booth_number": "부스 번호",
    "product_image_link": "제품 이미지",
    "company_logo_link": "로고",
    "homepage": "웹사이트",
    "exhibitor_sn": "참가사 SN",
    "product_id": "제품 ID",
    "search_keywords_kor": "검색 키워드",
    "search_keywords_eng": "검색 키워드(영문)",
    "drawing_info_company_name_kor": "도면상 회사명",
    "drawing_info_company_name_eng": "도면상 회사명(영문)",
}

# 원시 코드 컬럼은 대응 *_label_kor 등이 있으면 카드 부제에서 생략
_SUPPRESS_WHEN_LABEL: dict[str, str] = {
    "item_main_category": "item_main_category_label_kor",
    "item_sub_category": "item_sub_category_label_kor",
    "country_of_origin": "country_of_origin_label_kor",
}

_KV_CHUNK = re.compile(r"^([a-z][a-z0-9_]*)\s*:\s*(.+)$", re.I)

_TITLE_KEYS_PRODUCT = ("product_name_kor", "product_name_eng", "model_name", "company_name_kor", "company_name_eng")
_TITLE_KEYS_EXHIBITOR = ("company_name_kor", "company_name_eng", "drawing_info_company_name_kor", "product_name_kor")

_SUBTITLE_KEYS_PRODUCT = (
    "exhibition_category_label",
    "item_main_category_label_kor",
    "item_sub_category_label_kor",
    "manufacturer_kor",
    "country_of_origin_label_kor",
    "exhibit_hall_label_kor",
    "exhibit_status_label_kor",
    "exhibit_year",
    "booth_number",
)
_SUBTITLE_KEYS_EXHIBITOR = (
    "exhibition_category_label",
    "exhibit_hall_label_kor",
    "exhibit_status_label_kor",
    "country_label_kor",
    "booth_number",
    "item_main_category_label_kor",
    "item_sub_category_label_kor",
)


def _truncate(s: str, n: int) -> str:
    t = (s or "").strip()
    if len(t) <= n:
        return t
    return t[: n - 1].rstrip() + "…"


def _should_suppress_key(key: str, data: dict[str, str]) -> bool:
    alt = _SUPPRESS_WHEN_LABEL.get(key)
    if alt and (data.get(alt) or "").strip():
        return True
    return False


def _label_for_field(key: str) -> str:
    return _FIELD_LABEL_KO.get(key) or key.replace("_", " ")


def parse_kv_fields_from_text(text: str) -> dict[str, str]:
    """청크 본문에서 ``field: value`` / ``field: value / ...`` 패턴만 추출."""
    out: dict[str, str] = {}
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        for part in [p.strip() for p in raw.split(" / ") if p.strip()]:
            m = _KV_CHUNK.match(part)
            if not m:
                continue
            k = m.group(1).strip().lower()
            v = m.group(2).strip()
            if k and v:
                out[k] = v
    return out


def title_subtitle_from_kv(data: dict[str, str], *, entity_kind: str) -> tuple[str, str] | None:
    if not data:
        return None
    kind = (entity_kind or "").strip().lower()
    title_keys = _TITLE_KEYS_PRODUCT if kind == "exhibit_item" else _TITLE_KEYS_EXHIBITOR
    title = ""
    for tk in title_keys:
        v = (data.get(tk) or "").strip()
        if v:
            title = v
            break
    if not title:
        for fk in (
            "product_name_kor",
            "item_main_category_label_kor",
            "exhibition_category_label",
            "item_sub_category_label_kor",
        ):
            v = (data.get(fk) or "").strip()
            if v:
                title = v
                break
    if not title:
        return None

    sub_keys = _SUBTITLE_KEYS_PRODUCT if kind == "exhibit_item" else _SUBTITLE_KEYS_EXHIBITOR
    parts: list[str] = []
    used_title_key = next((tk for tk in title_keys if (data.get(tk) or "").strip() == title), None)
    for sk in sub_keys:
        if used_title_key and sk == used_title_key:
            continue
        if _should_suppress_key(sk, data):
            continue
        v = (data.get(sk) or "").strip()
        if not v:
            continue
        label = _label_for_field(sk)
        parts.append(f"{label}: {_truncate(v, 56)}")
        if len(" · ".join(parts)) >= 200:
            break
    subtitle = " · ".join(parts)[:220]
    return title[:200], subtitle


def extract_card_title_subtitle(content: str, *, entity_kind: str) -> tuple[str, str]:
    """본문이 구조화 필드면 한글 라벨 기반 제목·부제, 아니면 첫 줄 기반 폴백."""
    data = parse_kv_fields_from_text(content)
    got = title_subtitle_from_kv(data, entity_kind=entity_kind)
    if got:
        return got
    raw = str(content or "").strip()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    ext_fallback = ""
    title = lines[0] if lines else "검색 결과"
    subtitle = ""
    if len(lines) > 1:
        subtitle = " ".join(lines[1 : min(4, len(lines))])[:220]
    elif len(raw) > len(title):
        subtitle = raw[len(title) :].strip()[:220]
    return title[:200], subtitle


def build_cards_from_context_lines(
    context: str,
    *,
    query: str,
    max_cards: int = 8,
) -> list[dict[str, Any]]:
    """``apply_cutoff_and_build_context`` 가 만든 줄에서 ``external_id`` / ``content`` 를 뽑아 카드로 쓴다."""
    _ = query
    marker = ", content="
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in (context or "").splitlines():
        if marker not in line:
            continue
        head, tail = line.split(marker, 1)
        ext = ""
        if "external_id=" in head:
            ext = head.split("external_id=")[-1].strip()
        content = tail.strip()
        if not content and not ext:
            continue
        dedupe_key = f"{ext}|{content[:80]}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        kind = "exhibit_item" if "exhibit_item" in head.lower() else "exhibitor"
        title, subtitle = extract_card_title_subtitle(content, entity_kind=kind)
        if not title.strip() and ext:
            title = ext[:200]
        follow = f"{title}에 대해 더 자세히 알려줘"
        out.append(
            {
                "title": title[:200],
                "subtitle": subtitle or None,
                "entity_kind": kind,
                "follow_prompt": follow,
                "external_id": ext or None,
            }
        )
        if len(out) >= max_cards:
            break
    return out


def infer_entity_kind_from_table(table_name: str) -> str:
    t = (table_name or "").lower()
    if "exhibit_item" in t or "exhibititem" in t:
        return "exhibit_item"
    return "exhibitor"


def build_cards_from_rows(
    rows: list[dict[str, Any]],
    *,
    query: str,
    max_cards: int = 10,
) -> list[dict[str, Any]]:
    _ = query
    out: list[dict[str, Any]] = []
    for r in (rows or [])[:max_cards]:
        content = str(r.get("content") or "").strip()
        ext = str(r.get("external_id") or "").strip()
        kind = infer_entity_kind_from_table(str(r.get("table_name") or ""))
        title, subtitle = extract_card_title_subtitle(content, entity_kind=kind)
        if not title.strip() and ext:
            title = ext[:200]
        follow = f"{title}에 대해 더 자세히 알려줘"
        card: dict[str, Any] = {
            "title": title[:200],
            "subtitle": (subtitle or None) if subtitle else None,
            "entity_kind": kind,
            "follow_prompt": follow,
            "external_id": ext or None,
        }
        out.append(card)
    return out
