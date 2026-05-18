"""``external_id`` 직접 조회 (KPRINT exhibitor / exhibit item)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.logger import get_logger

logger = get_logger(__name__)
_ENTITY_DESC_FULL_MAX = 50000


def entity_description_full(raw: Any) -> str | None:
    s = str(raw or "").strip()
    if not s:
        return None
    if len(s) > _ENTITY_DESC_FULL_MAX:
        s = s[:_ENTITY_DESC_FULL_MAX].rstrip() + "…"
    return s


def direct_lookup_results_by_external_id_sync(*, engine, external_id: str) -> list[dict[str, Any]]:
    ext = (external_id or "").strip()
    if not ext:
        return []

    exhib_sql = text(
        """
        SELECT external_id,
               company_name_kor, company_name_eng, homepage,
               exhibition_category_label, booth_number, exhibit_hall_label_kor,
               country_label_kor, company_address_kor,
               exhibition_manager_tel,
               company_description_kor
          FROM kprint_exhibitor
         WHERE external_id = :ext
         LIMIT 1
        """
    )
    item_sql = text(
        """
        SELECT external_id,
               product_name_kor, product_name_eng,
               manufacturer_kor, model_name,
               item_main_category_label_kor, item_sub_category_label_kor,
               exhibition_category_label, exhibit_hall_label_kor,
               company_name_kor,
               product_description_kor
          FROM kprint_exhibit_item
         WHERE external_id = :ext
         LIMIT 1
        """
    )

    def _kv_ko(**kwargs: Any) -> str:
        lines: list[str] = []
        for k, v in kwargs.items():
            s = str(v or "").strip()
            if not s:
                continue
            lines.append(f"{k}: {s}")
        return "\n".join(lines).strip()

    out: list[dict[str, Any]] = []
    with engine.connect() as conn:
        r1 = conn.execute(exhib_sql, {"ext": ext}).mappings().first()
        if r1:
            cdesc_full = entity_description_full(r1.get("company_description_kor"))
            entity_detail = {
                "entity_type": "company",
                "external_id": ext,
                "company_name": (r1.get("company_name_kor") or r1.get("company_name_eng") or "").strip() or None,
                "one_liner": ((cdesc_full or "")[:120] or None),
                "description": cdesc_full,
                "booth": (str(r1.get("booth_number") or "").strip() or None),
                "hall": (str(r1.get("exhibit_hall_label_kor") or "").strip() or None),
                "category": (str(r1.get("exhibition_category_label") or "").strip() or None),
                "contact": (str(r1.get("exhibition_manager_tel") or "").strip() or None),
                "website": (str(r1.get("homepage") or "").strip() or None),
            }
            content = _kv_ko(
                회사명=entity_detail.get("company_name"),
                부스=entity_detail.get("booth"),
                홀=entity_detail.get("hall"),
                분야=entity_detail.get("category"),
                연락처=entity_detail.get("contact"),
                웹사이트=entity_detail.get("website"),
            )
            out.append(
                {
                    "table_name": "kprint_exhibitor",
                    "external_id": ext,
                    "lang": "ko",
                    "model": "direct",
                    "chunk_typ": "profile",
                    "source_field": "direct_lookup",
                    "chunk_index": 0,
                    "content": content,
                    "entity_type": "company",
                    "entity_detail": entity_detail,
                    "distance": 0.0,
                    "score": 1.0,
                }
            )
        try:
            r2 = conn.execute(item_sql, {"ext": ext}).mappings().first()
            if r2:
                pdesc_full = entity_description_full(r2.get("product_description_kor"))
                entity_detail = {
                    "entity_type": "product",
                    "external_id": ext,
                    "product_name": (r2.get("product_name_kor") or r2.get("product_name_eng") or "").strip() or None,
                    "one_liner": ((pdesc_full or "")[:120] or None),
                    "description": pdesc_full,
                    "manufacturer": (str(r2.get("manufacturer_kor") or "").strip() or None),
                    "model_name": (str(r2.get("model_name") or "").strip() or None),
                    "category": (
                        str(r2.get("item_main_category_label_kor") or r2.get("exhibition_category_label") or "").strip()
                        or None
                    ),
                    "location": (str(r2.get("exhibit_hall_label_kor") or "").strip() or None),
                }
                content = _kv_ko(
                    제품명=entity_detail.get("product_name"),
                    제조사=entity_detail.get("manufacturer"),
                    모델=entity_detail.get("model_name"),
                    카테고리=entity_detail.get("category"),
                    전시위치=entity_detail.get("location"),
                )
                out.append(
                    {
                        "table_name": "kprint_exhibit_item",
                        "external_id": ext,
                        "lang": "ko",
                        "model": "direct",
                        "chunk_typ": "profile",
                        "source_field": "direct_lookup",
                        "chunk_index": 0,
                        "content": content,
                        "entity_type": "product",
                        "entity_detail": entity_detail,
                        "distance": 0.0,
                        "score": 1.0,
                    }
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("[direct_lookup] exhibit_item lookup skipped ext=%s err=%s", ext, e)
    return out
