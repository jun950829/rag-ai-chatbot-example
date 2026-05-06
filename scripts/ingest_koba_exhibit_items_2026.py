#!/usr/bin/env python3
"""Ingest `data/KPRINT_ExhibitItemsExport_2025.csv` into `kprint_exhibit_item`."""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass

from sqlalchemy import select

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_ROOT = os.path.join(PROJECT_ROOT, "main")
sys.path.insert(0, MAIN_ROOT)
sys.path.insert(1, PROJECT_ROOT)
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _scripts_dir)

import ingest_db_env  # noqa: E402

ingest_db_env.ensure_sync_database_url(main_root=MAIN_ROOT)

from app.db import SessionLocal  # noqa: E402
from app.kprint.models import KprintExhibitItem as KobaExhibitItem  # noqa: E402


def _clean_excel_export_value(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    if v == "":
        return None
    if v.startswith('="') and v.endswith('"') and len(v) >= 4:
        v = v[2:-1]
    if v.startswith('"=""') and v.endswith('"""') and len(v) >= 8:
        v = v[4:-3]
    v = v.strip()
    return v or None


def _parse_int(value: str | None) -> int | None:
    v = _clean_excel_export_value(value)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _parse_str(value: str | None) -> str | None:
    return _clean_excel_export_value(value)


def _external_id_for_row(row: dict[str, str]) -> str | None:
    pid = _parse_str(row.get("productId")) or ""
    sn = _parse_str(row.get("sn")) or ""
    if not sn:
        return None
    if pid:
        return f"{pid}_{sn}"
    return sn


def _row_to_model_fields(row: dict[str, str]) -> dict[str, object]:
    ext = _external_id_for_row(row)
    return {
        "external_id": ext,
        "product_id": _parse_str(row.get("productId")),
        "exhibitor_sn": _parse_str(row.get("sn")),
        "item_main_category": _parse_str(row.get("itemMainCategory")),
        "item_main_category_label_kor": _parse_str(row.get("itemMainCategoryLabelKor")),
        "item_main_category_label_eng": _parse_str(row.get("itemMainCategoryLabelEng")),
        "item_sub_category": _parse_str(row.get("itemSubCategory")),
        "item_sub_category_label_kor": _parse_str(row.get("itemSubCategoryLabelKor")),
        "item_sub_category_label_eng": _parse_str(row.get("itemSubCategoryLabelEng")),
        "product_name_kor": _parse_str(row.get("productNameKor")),
        "product_name_eng": _parse_str(row.get("productNameEng")),
        "search_keywords_kor": _parse_str(row.get("searchKeywordsKor")),
        "search_keywords_eng": _parse_str(row.get("searchKeywordsEng")),
        "country_of_origin": _parse_str(row.get("countryOfOrigin")),
        "country_of_origin_label_kor": _parse_str(row.get("countryOfOriginLabelKor")),
        "country_of_origin_label_eng": _parse_str(row.get("countryOfOriginLabelEng")),
        "model_name": _parse_str(row.get("modelName")),
        "manufacturer_kor": _parse_str(row.get("manufacturerKor")),
        "manufacturer_eng": _parse_str(row.get("manufacturerEng")),
        "product_description_kor": _parse_str(row.get("productDescriptionKor")),
        "product_description_eng": _parse_str(row.get("productDescriptionEng")),
        "certification_status_kor": _parse_str(row.get("certificationStatusKor")),
        "certification_status_eng": _parse_str(row.get("certificationStatusEng")),
        "company_name_kor": _parse_str(row.get("companyNameKor")),
        "company_name_eng": _parse_str(row.get("companyNameEng")),
        "exhibit_year": _parse_int(row.get("exhibitYear")),
        "exhibition_category_label": _parse_str(row.get("exhibitionCategoryLabel")),
        "exhibit_hall": _parse_str(row.get("exhibitHall")),
        "exhibit_hall_label_kor": _parse_str(row.get("exhibitHallLabelKor")),
        "exhibit_hall_label_eng": _parse_str(row.get("exhibitHallLabelEng")),
        "exhibit_status": _parse_str(row.get("exhibitStatus")),
        "exhibit_status_label_kor": _parse_str(row.get("exhibitStatusLabelKor")),
        "exhibit_status_label_eng": _parse_str(row.get("exhibitStatusLabelEng")),
        "product_image_link": _parse_str(row.get("productImageLink")),
    }


@dataclass(frozen=True)
class IngestStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0


def upsert_item(db, fields: dict[str, object]) -> bool:
    ext = fields.get("external_id")
    if not ext:
        raise ValueError("external_id required")
    obj = db.scalar(select(KobaExhibitItem).where(KobaExhibitItem.external_id == ext))
    created = obj is None
    if obj is None:
        obj = KobaExhibitItem()
        db.add(obj)
    for key, val in fields.items():
        setattr(obj, key, val)
    return created


def reset_rows() -> int:
    with SessionLocal() as db:
        deleted = db.query(KobaExhibitItem).delete()  # noqa: S608
        db.commit()
        return int(deleted or 0)


def ingest_csv(*, csv_path: str, limit: int | None, commit_every: int, dry_run: bool) -> IngestStats:
    created = updated = skipped = 0
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f, SessionLocal() as db:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise RuntimeError("CSV header not found.")
        for idx, row in enumerate(reader, start=1):
            if limit is not None and idx > limit:
                break
            fields = _row_to_model_fields(row)
            if not fields.get("external_id"):
                skipped += 1
                continue
            is_created = upsert_item(db, fields)
            if is_created:
                created += 1
            else:
                updated += 1
            if commit_every > 0 and (idx % commit_every == 0):
                if not dry_run:
                    db.commit()
                else:
                    db.rollback()
        if not dry_run:
            db.commit()
        else:
            db.rollback()
    return IngestStats(created=created, updated=updated, skipped=skipped)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest KPRINT_ExhibitItemsExport_2025.csv into kprint_exhibit_item.")
    parser.add_argument(
        "--path",
        default=os.path.join("data", "KPRINT_ExhibitItemsExport_2025.csv"),
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--commit-every", type=int, default=250)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.reset:
        print(f"reset_complete deleted={reset_rows()}")

    stats = ingest_csv(
        csv_path=args.path,
        limit=args.limit,
        commit_every=args.commit_every,
        dry_run=args.dry_run,
    )
    print("ingest_complete")
    print(f"created={stats.created} updated={stats.updated} skipped={stats.skipped}")


if __name__ == "__main__":
    main()
