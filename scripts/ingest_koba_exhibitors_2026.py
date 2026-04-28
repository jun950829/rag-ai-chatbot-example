#!/usr/bin/env python3
"""Ingest `data/KPRINT_ExhibitorsExport_2025.csv` into `kprint_exhibitor`."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass

from sqlalchemy import select

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_ROOT = os.path.join(PROJECT_ROOT, "main")
sys.path.insert(0, MAIN_ROOT)
sys.path.insert(1, PROJECT_ROOT)

from app.db import SessionLocal  # noqa: E402
from app.kprint.models import KprintExhibitor as KobaExhibitor  # noqa: E402


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


def _parse_list_str(value: str | None) -> list[str]:
    v = _clean_excel_export_value(value)
    if not v:
        return []
    if v.startswith("[") and v.endswith("]"):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    return [part.strip() for part in v.split(",") if part.strip()]


def _parse_list_int(value: str | None) -> list[int]:
    v = _clean_excel_export_value(value)
    if not v:
        return []
    if v.startswith("[") and v.endswith("]"):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                out: list[int] = []
                for x in parsed:
                    try:
                        out.append(int(x))
                    except Exception:
                        continue
                return out
        except Exception:
            pass
    out = []
    for part in v.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def _row_to_model_fields(row: dict[str, str]) -> dict[str, object]:
    return {
        "external_id": _parse_str(row.get("sn")),
        "company_name_kor": _parse_str(row.get("companyNameKor")),
        "company_name_eng": _parse_str(row.get("companyNameEng")),
        "exhibit_year": _parse_int(row.get("exhibitYear")),
        "exhibition_category_label": _parse_str(row.get("exhibitionCategoryLabel")),
        "booth_number": _parse_str(row.get("boothNumber")),
        "homepage": _parse_str(row.get("homepage")),
        "country_code": _parse_str(row.get("countryCode")),
        "country_label_kor": _parse_str(row.get("countryLabelKor")),
        "country_label_eng": _parse_str(row.get("countryLabelEng")),
        "exhibit_hall_code": _parse_str(row.get("exhibitHallCode")),
        "exhibit_hall_label_kor": _parse_str(row.get("exhibitHallLabelKor")),
        "exhibit_hall_label_eng": _parse_str(row.get("exhibitHallLabelEng")),
        "exhibit_status_code": _parse_str(row.get("exhibitStatusCode")),
        "exhibit_status_label_kor": _parse_str(row.get("exhibitStatusLabelKor")),
        "exhibit_status_label_eng": _parse_str(row.get("exhibitStatusLabelEng")),
        "badge_list": _parse_list_int(row.get("badgeList")),
        "badge_label_kor_list": _parse_list_str(row.get("badgeLabelKorList")),
        "badge_label_eng_list": _parse_list_str(row.get("badgeLabelEngList")),
        "item_main_category_label_kor_list": _parse_list_str(row.get("itemMainCategoryLabelKorList")),
        "item_main_category_label_eng_list": _parse_list_str(row.get("itemMainCategoryLabelEngList")),
        "item_sub_category_label_kor_list": _parse_list_str(row.get("itemSubCategoryLabelKorList")),
        "item_sub_category_label_eng_list": _parse_list_str(row.get("itemSubCategoryLabelEngList")),
        "company_address_kor": _parse_str(row.get("companyAddressKor")),
        "company_address_eng": _parse_str(row.get("companyAddressEng")),
        "exhibition_manager_tel": _parse_str(row.get("exhibitionManagerTel")),
        "company_description_kor": _parse_str(row.get("companyDescriptionKor")),
        "company_description_eng": _parse_str(row.get("companyDescriptionEng")),
        "drawing_info_company_name_kor": _parse_str(row.get("drawingInfoCompanyNameKor")),
        "drawing_info_company_name_eng": _parse_str(row.get("drawingInfoCompanyNameEng")),
        "drawing_info_company_x_coordinate_kor": _parse_int(row.get("drawingInfoCompanyXCoordinateKor")),
        "drawing_info_company_x_coordinate_eng": _parse_int(row.get("drawingInfoCompanyXCoordinateEng")),
        "drawing_info_company_y_coordinate_kor": _parse_int(row.get("drawingInfoCompanyYCoordinateKor")),
        "drawing_info_company_y_coordinate_eng": _parse_int(row.get("drawingInfoCompanyYCoordinateEng")),
        "company_logo_link": _parse_str(row.get("companyLogoLink")),
    }


@dataclass(frozen=True)
class IngestStats:
    created: int = 0
    updated: int = 0
    skipped: int = 0


def upsert_exhibitor(db, fields: dict[str, object]) -> bool:
    ext = fields.get("external_id")
    if not ext:
        raise ValueError("external_id required")
    obj = db.scalar(select(KobaExhibitor).where(KobaExhibitor.external_id == ext))
    created = obj is None
    if obj is None:
        obj = KobaExhibitor()
        db.add(obj)
    for key, val in fields.items():
        setattr(obj, key, val)
    return created


def reset_rows() -> int:
    with SessionLocal() as db:
        deleted = db.query(KobaExhibitor).delete()  # noqa: S608
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
            is_created = upsert_exhibitor(db, fields)
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
    parser = argparse.ArgumentParser(description="Ingest KPRINT_ExhibitorsExport_2025.csv into kprint_exhibitor.")
    parser.add_argument(
        "--path",
        default=os.path.join("data", "KPRINT_ExhibitorsExport_2025.csv"),
        help="Path to the CSV file.",
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
