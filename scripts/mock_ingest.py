#!/usr/bin/env python3
"""
Seed a small set of demo company/product rows.

This is intentionally simple and meant as an example ingestion script:

1. build normalized payloads
2. upsert the parent company
3. upsert child products
4. commit once

Use this as a reference for future ingestion scripts, not as production logic.
"""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_ROOT = os.path.join(PROJECT_ROOT, "main")
sys.path.insert(0, MAIN_ROOT)
sys.path.insert(1, PROJECT_ROOT)

from app.company.helpers import apply_company_fields, find_company_by_external_id
from app.company.models import Company
from app.company.serializers import CompanyCreate
from app.db import SessionLocal
from app.product.helpers import apply_product_fields, find_product_by_external_id
from app.product.models import Product
from app.product.serializers import ProductCreate


DEMO_COMPANY_EXTERNAL_ID = "demo-company-001"
DEMO_PRODUCT_EXTERNAL_IDS = ["demo-product-001", "demo-product-002"]


def build_demo_company() -> CompanyCreate:
    return CompanyCreate(
        external_id=DEMO_COMPANY_EXTERNAL_ID,
        name_kor="데모 메디컬",
        name_eng="Demo Medical",
        desc_kor="RAG 템플릿 테스트용 참가기업 데이터입니다.",
        desc_eng="Demo exhibitor data used for the RAG template starter.",
        homepage="https://example.com/demo-medical",
        tel="+82-2-555-0100",
        exhibit_year=2026,
        exhibition_category="DEMO EXPO",
        booth_number="A-101",
        exhibit_hall_label_kor="A홀",
        exhibit_hall_label_eng="Hall A",
        country_code="KR",
        country_label_kor="대한민국",
        country_label_eng="Korea, Republic of",
        address_kor="서울시 강남구 테헤란로 100",
        address_eng="100 Teheran-ro, Gangnam-gu, Seoul",
        item_main_categories_kor=["영상장비", "진단기기"],
        item_main_categories_eng=["Imaging", "Diagnostics"],
        item_sub_categories_kor=["초음파", "디지털 헬스"],
        item_sub_categories_eng=["Ultrasound", "Digital Health"],
    )


def build_demo_products(company_id) -> list[ProductCreate]:
    return [
        ProductCreate(
            external_id=DEMO_PRODUCT_EXTERNAL_IDS[0],
            company_id=company_id,
            name_kor="데모 초음파 스캐너",
            name_eng="Demo Ultrasound Scanner",
            image_url="https://example.com/assets/demo-ultrasound.png",
            description_kor="휴대형 검사 환경을 위한 데모 초음파 장비입니다.",
            description_eng="A demo ultrasound device for portable examination workflows.",
            certification_kor="국내용 데모 인증",
            certification_eng="Demo domestic certification",
            keywords_kor="초음파,진단,휴대형",
            keywords_eng="ultrasound,diagnostic,portable",
            main_category_code="11",
            main_category_kor="영상장비",
            main_category_eng="Imaging",
            sub_category_code="11.01",
            sub_category_kor="초음파",
            sub_category_eng="Ultrasound",
            model_name="DUS-100",
            manufacturer_kor="데모 메디컬 제조부",
            manufacturer_eng="Demo Medical Manufacturing",
            country_of_origin_code="KR",
            country_of_origin_kor="대한민국",
            country_of_origin_eng="Korea, Republic of",
            exhibit_year=2026,
            exhibition_category="DEMO EXPO",
            exhibit_hall_label_kor="A홀",
            exhibit_hall_label_eng="Hall A",
        ),
        ProductCreate(
            external_id=DEMO_PRODUCT_EXTERNAL_IDS[1],
            company_id=company_id,
            name_kor="데모 원격 모니터링 플랫폼",
            name_eng="Demo Remote Monitoring Platform",
            image_url="https://example.com/assets/demo-monitoring.png",
            description_kor="원격 환자 모니터링 시나리오를 위한 예시 플랫폼입니다.",
            description_eng="A sample platform for remote patient monitoring scenarios.",
            certification_kor="해외 테스트 인증",
            certification_eng="Demo international certification",
            keywords_kor="원격모니터링,디지털헬스,플랫폼",
            keywords_eng="remote monitoring,digital health,platform",
            main_category_code="21",
            main_category_kor="디지털 헬스",
            main_category_eng="Digital Health",
            sub_category_code="21.03",
            sub_category_kor="원격진료 지원",
            sub_category_eng="Remote Care Support",
            model_name="DRM-200",
            manufacturer_kor="데모 메디컬 소프트웨어팀",
            manufacturer_eng="Demo Medical Software Team",
            country_of_origin_code="KR",
            country_of_origin_kor="대한민국",
            country_of_origin_eng="Korea, Republic of",
            exhibit_year=2026,
            exhibition_category="DEMO EXPO",
            exhibit_hall_label_kor="A홀",
            exhibit_hall_label_eng="Hall A",
        ),
    ]


def upsert_company(payload: CompanyCreate) -> tuple[Company, bool]:
    with SessionLocal() as db:
        company = find_company_by_external_id(db, payload.external_id)
        created = company is None

        if company is None:
            company = Company()
            db.add(company)

        apply_company_fields(company, payload)
        db.commit()
        db.refresh(company)
        return company, created


def upsert_products(products: list[ProductCreate]) -> tuple[int, int]:
    created = 0
    updated = 0

    with SessionLocal() as db:
        for payload in products:
            product = find_product_by_external_id(db, payload.external_id)
            is_created = product is None

            if product is None:
                product = Product()
                db.add(product)

            apply_product_fields(product, payload)

            if is_created:
                created += 1
            else:
                updated += 1

        db.commit()

    return created, updated


def reset_demo_rows() -> None:
    with SessionLocal() as db:
        for external_id in DEMO_PRODUCT_EXTERNAL_IDS:
            product = find_product_by_external_id(db, external_id)
            if product is not None:
                db.delete(product)

        company = find_company_by_external_id(db, DEMO_COMPANY_EXTERNAL_ID)
        if company is not None:
            db.delete(company)

        db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a small set of demo company/product rows.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing demo company/products before re-seeding.",
    )
    args = parser.parse_args()

    if args.reset:
        reset_demo_rows()

    company, company_created = upsert_company(build_demo_company())
    product_created, product_updated = upsert_products(build_demo_products(company.id))

    print("mock_ingest_complete")
    print(f"company_id={company.id}")
    print(f"company_created={company_created}")
    print(f"products_created={product_created}")
    print(f"products_updated={product_updated}")


if __name__ == "__main__":
    main()
