"""제품/업체 검색(RAG) 전용 entity enrichment 레이어.

중요:
- FAQ 시스템과 무관 (절대 수정/의존 X)
- pgvector/embedding/LLM 여부와 관계 없이, external_id로 실 entity 테이블을 조회해
  구조화된 entity_detail을 붙여 응답 품질을 안정화한다.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from sqlalchemy import text

logger = logging.getLogger(__name__)


def infer_entity_type_from_table(table_name: str) -> str:
    t = (table_name or "").lower()
    if "exhibit_item" in t or "exhibititem" in t:
        return "product"
    if "exhibitor" in t:
        return "company"
    return "company"


# DB 본문(회사/제품 소개)은 LLM·템플릿에서 전문 노출하므로 상한만 크게 둔다.
_DESCRIPTION_FULL_MAX = 50000


def _clean(v: Any, *, max_len: int = 400) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("\u0000", "").strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip() + "…"
    return s


def _norm_locale(language: str | None) -> str:
    """entity_detail·카드용 로케일 (ko / en 만 지원)."""
    return "en" if (language or "").strip().lower() == "en" else "ko"


def _pick_i18n(*, locale: str, en_val: Any, ko_val: Any, max_len: int | None = None) -> str | None:
    """로케일에 맞게 eng/ko 값을 고르고, 비면 다른 쪽으로 폴백."""

    ml = max_len if max_len is not None else 400
    if locale == "en":
        return _clean(en_val, max_len=ml) or _clean(ko_val, max_len=ml)
    return _clean(ko_val, max_len=ml) or _clean(en_val, max_len=ml)


def load_entity_detail_sync(
    *, engine, external_id: str, entity_type: str, language: str = "ko"
) -> dict[str, Any] | None:
    """external_id + type(company/product)로 실 entity 테이블에서 상세 조회."""

    ext = (external_id or "").strip()
    if not ext:
        return None
    typ = (entity_type or "").strip() or "company"
    loc = _norm_locale(language)

    if typ == "product":
        sql = text(
            """
            SELECT external_id,
                   product_name_kor, product_name_eng,
                   manufacturer_kor, manufacturer_eng,
                   model_name,
                   item_main_category_label_kor, item_main_category_label_eng,
                   item_sub_category_label_kor, item_sub_category_label_eng,
                   exhibit_hall_label_kor, exhibit_hall_label_eng,
                   exhibition_category_label,
                   company_name_kor, company_name_eng,
                   product_description_kor, product_description_eng
              FROM kprint_exhibit_item
             WHERE external_id = :ext
             LIMIT 1
            """
        )
        with engine.connect() as conn:
            r = conn.execute(sql, {"ext": ext}).mappings().first()
        if not r:
            return None
        company_for_join = _pick_i18n(
            locale=loc,
            en_val=r.get("company_name_eng"),
            ko_val=r.get("company_name_kor"),
        )
        contact = None
        website = None
        booth = None
        hall = None
        if company_for_join:
            with engine.connect() as conn:
                r2 = conn.execute(
                    text(
                        """
                        SELECT homepage, exhibition_manager_tel, booth_number,
                               exhibit_hall_label_kor, exhibit_hall_label_eng
                          FROM kprint_exhibitor
                         WHERE company_name_kor = :n OR company_name_eng = :n
                         LIMIT 1
                        """
                    ),
                    {"n": company_for_join},
                ).mappings().first()
            if r2:
                contact = _clean(r2.get("exhibition_manager_tel"), max_len=120)
                website = _clean(r2.get("homepage"), max_len=200)
                booth = _clean(r2.get("booth_number"), max_len=80)
                hall = _pick_i18n(
                    locale=loc,
                    en_val=r2.get("exhibit_hall_label_eng"),
                    ko_val=r2.get("exhibit_hall_label_kor"),
                    max_len=120,
                )
        desc_full = _pick_i18n(
            locale=loc,
            en_val=r.get("product_description_eng"),
            ko_val=r.get("product_description_kor"),
            max_len=_DESCRIPTION_FULL_MAX,
        )
        one_liner = _pick_i18n(
            locale=loc,
            en_val=r.get("product_description_eng"),
            ko_val=r.get("product_description_kor"),
            max_len=120,
        )
        return {
            "entity_type": "product",
            "external_id": ext,
            "product_name": _pick_i18n(
                locale=loc, en_val=r.get("product_name_eng"), ko_val=r.get("product_name_kor")
            ),
            "one_liner": one_liner,
            "description": desc_full,
            "manufacturer": _pick_i18n(
                locale=loc,
                en_val=r.get("manufacturer_eng"),
                ko_val=r.get("manufacturer_kor"),
            )
            or _pick_i18n(
                locale=loc,
                en_val=r.get("company_name_eng"),
                ko_val=r.get("company_name_kor"),
            ),
            "model_name": _clean(r.get("model_name"), max_len=120),
            "category": _pick_i18n(
                locale=loc,
                en_val=r.get("item_main_category_label_eng"),
                ko_val=r.get("item_main_category_label_kor"),
            )
            or _clean(r.get("exhibition_category_label")),
            "features": _pick_i18n(
                locale=loc,
                en_val=r.get("item_sub_category_label_eng"),
                ko_val=r.get("item_sub_category_label_kor"),
                max_len=180,
            ),
            "location": _pick_i18n(
                locale=loc,
                en_val=r.get("exhibit_hall_label_eng"),
                ko_val=r.get("exhibit_hall_label_kor"),
                max_len=120,
            )
            or (" ".join([x for x in [hall, booth] if x]).strip() or None),
            "company_name": _pick_i18n(
                locale=loc, en_val=r.get("company_name_eng"), ko_val=r.get("company_name_kor")
            ),
            "contact": contact,
            "website": website,
        }

    # company
    sql = text(
        """
        SELECT external_id,
               company_name_kor, company_name_eng,
               company_description_kor, company_description_eng,
               exhibition_category_label,
               booth_number,
               exhibit_hall_label_kor, exhibit_hall_label_eng,
               exhibition_manager_tel,
               homepage,
               company_address_kor, company_address_eng
          FROM kprint_exhibitor
         WHERE external_id = :ext
         LIMIT 1
        """
    )
    with engine.connect() as conn:
        r = conn.execute(sql, {"ext": ext}).mappings().first()
    if not r:
        return None
    company_key = _pick_i18n(
        locale=loc, en_val=r.get("company_name_eng"), ko_val=r.get("company_name_kor")
    )
    majors: list[str] = []
    if company_key:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        """
                        SELECT product_name_kor, product_name_eng
                          FROM kprint_exhibit_item
                         WHERE company_name_kor = :n OR company_name_eng = :n
                         LIMIT 3
                        """
                    ),
                    {"n": company_key},
                )
                .mappings()
                .all()
            )
        for rr in rows:
            pn = _pick_i18n(
                locale=loc,
                en_val=rr.get("product_name_eng"),
                ko_val=rr.get("product_name_kor"),
            )
            if pn:
                majors.append(pn)
    desc_full = _pick_i18n(
        locale=loc,
        en_val=r.get("company_description_eng"),
        ko_val=r.get("company_description_kor"),
        max_len=_DESCRIPTION_FULL_MAX,
    )
    one_liner = _pick_i18n(
        locale=loc,
        en_val=r.get("company_description_eng"),
        ko_val=r.get("company_description_kor"),
        max_len=120,
    )
    return {
        "entity_type": "company",
        "external_id": ext,
        "company_name": _pick_i18n(
            locale=loc, en_val=r.get("company_name_eng"), ko_val=r.get("company_name_kor")
        ),
        "one_liner": one_liner,
        "booth": _clean(r.get("booth_number"), max_len=80),
        "hall": _pick_i18n(
            locale=loc,
            en_val=r.get("exhibit_hall_label_eng"),
            ko_val=r.get("exhibit_hall_label_kor"),
            max_len=120,
        ),
        "category": _clean(r.get("exhibition_category_label"), max_len=160),
        "contact": _clean(r.get("exhibition_manager_tel"), max_len=120),
        "website": _clean(r.get("homepage"), max_len=200),
        "address": _pick_i18n(
            locale=loc,
            en_val=r.get("company_address_eng"),
            ko_val=r.get("company_address_kor"),
            max_len=200,
        ),
        "description": desc_full,
        "major_products": majors[:3],
    }


def enrich_results_with_entity_detail_sync(
    *, engine, results: list[dict[str, Any]], language: str = "ko"
) -> list[dict[str, Any]]:
    """retrieval 결과 rows에 entity_detail을 attach한다.

    - external_id 기준으로 한 번만 조회 후, 동일 external_id row에 재사용
    - 내부 메타는 answer로 노출하지 않고 entity_detail만 템플릿/LLM 포맷터가 사용한다.
    - language=en 이면 DB의 *_eng 컬럼을 우선해 답변·컨텍스트에 실릴 값을 맞춘다.
    """

    loc = _norm_locale(language)
    cache: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    out: list[dict[str, Any]] = []
    for r in results or []:
        rr = dict(r)
        ext = (rr.get("external_id") or "").strip()
        tn = str(rr.get("table_name") or "")
        typ = infer_entity_type_from_table(tn)
        rr["entity_type"] = typ
        if ext:
            k = (typ, ext, loc)
            if k not in cache:
                logger.info(
                    "[ENTITY_ENRICH] external_id=%s entity_type=%s locale=%s loaded_from=%s",
                    ext,
                    typ,
                    loc,
                    "kprint_exhibitor" if typ == "company" else "kprint_exhibit_item",
                )
                cache[k] = load_entity_detail_sync(
                    engine=engine, external_id=ext, entity_type=typ, language=loc
                )
            rr["entity_detail"] = cache[k]
        out.append(rr)
    return out


def merged_entity_context(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """external_id 기준으로 profile/evidence를 entity 단위로 merge한 요약 컨텍스트를 만든다."""

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for r in results or []:
        ext = (r.get("external_id") or "").strip()
        if not ext:
            continue
        typ = str(r.get("entity_type") or infer_entity_type_from_table(str(r.get("table_name") or "")))
        key = (typ, ext)
        m = merged.get(key)
        if not m:
            m = {
                "entity_type": typ,
                "external_id": ext,
                "entity_detail": r.get("entity_detail"),
                "profile_chunks": 0,
                "evidence_chunks": 0,
                "evidence_snippets": [],
            }
        if str(r.get("chunk_typ") or "") == "profile":
            m["profile_chunks"] = int(m.get("profile_chunks") or 0) + 1
        else:
            m["evidence_chunks"] = int(m.get("evidence_chunks") or 0) + 1
            # evidence는 raw를 그대로 노출하지 않고, 짧은 스니펫으로만(내부 키/컬럼명/점수 제거)
            c = str(r.get("content") or "").strip().replace("\n", " ")
            if c:
                # key:value 형태(컬럼명처럼 보이는) 제거
                c = re.sub(r"\b[a-z_]{3,}\s*:\s*", "", c)
                c = c.strip()
                if c:
                    m["evidence_snippets"].append(c[:120])
        merged[key] = m

    out = list(merged.values())
    for m in out:
        logger.info(
            "[ENTITY_MERGE] external_id=%s entity_type=%s profile_chunks=%s evidence_chunks=%s",
            m.get("external_id"),
            m.get("entity_type"),
            m.get("profile_chunks"),
            m.get("evidence_chunks"),
        )
    # profile chunk가 많은/먼저 등장한 엔티티를 우선으로 삼기 위해 간단 정렬
    out.sort(key=lambda x: (-(int(x.get("profile_chunks") or 0)), -(int(x.get("evidence_chunks") or 0))))
    return out

