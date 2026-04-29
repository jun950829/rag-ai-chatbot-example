#!/usr/bin/env python3
"""``docs/kprint QA bot_초안.csv`` → ``kprint_qa_quickmenu`` 테이블 적재.

사전 조건:
  1) Alembic 마이그레이션 ``20260430_kprint_qa_quickmenu`` 적용
  2) ``DATABASE_URL`` / 앱 설정과 동일한 DB에 연결

동작:
  - CSV 헤더 컬럼을 읽어 행 단위로 UPSERT (PK: ``qna_code``)
  - CSV ``user`` 컬럼 → DB ``qa_user`` (PostgreSQL 예약어 회피)
  - ``primary_question``: TRUE/true/1/Y 등을 true 로 파싱

카테고리 UI 힌트:
  - ``primary_question = true`` 인 행을 메인 1차 버튼 후보로 쓸 수 있음
  - 다음 뎁스는 ``parent_id``, ``depth``, ``follow_question*`` 코드로 앱에서 조합
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from typing import Any

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_ROOT = os.path.join(PROJECT_ROOT, "main")
sys.path.insert(0, MAIN_ROOT)
sys.path.insert(1, PROJECT_ROOT)

from sqlalchemy import delete, func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.db.models.kprint_qa_quickmenu import KprintQaQuickmenu  # noqa: E402


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v if v else None


def _parse_bool_primary(raw: str | None) -> bool:
    if raw is None:
        return False
    s = raw.strip().lower()
    return s in {"true", "1", "yes", "y", "t"}


def _parse_int(raw: str | None) -> int | None:
    v = _strip(raw)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def _csv_row_to_db_dict(row: dict[str, str]) -> dict[str, Any]:
    """DictReader 한 줄 → ``KprintQaQuickmenu`` 컬럼 dict."""
    code = _strip(row.get("qna_code"))
    if not code:
        raise ValueError("qna_code 가 비어 있음")
    return {
        "qna_code": code,
        "primary_question": _parse_bool_primary(row.get("primary_question")),
        "parent_id": _strip(row.get("parent_id")),
        "depth": _parse_int(row.get("depth")),
        "quickmenu_label": _strip(row.get("quickmenu_label")),
        "qa_user": _strip(row.get("user")),
        "domain": _strip(row.get("domain")),
        "category": _strip(row.get("category")),
        "subcategory": _strip(row.get("subcategory")),
        "question_sample": _strip(row.get("question_sample")),
        "answer_sample": _strip(row.get("answer_sample")),
        "links": _strip(row.get("links")),
        "utm": _strip(row.get("utm")),
        "follow_question1": _strip(row.get("follow_question1")),
        "follow_question2": _strip(row.get("follow_question2")),
        "follow_question3": _strip(row.get("follow_question3")),
        "follow_question4": _strip(row.get("follow_question4")),
        "follow_question5_formoreinformation": _strip(row.get("follow_question5_formoreinformation")),
        "default_quickmenu": _strip(row.get("default_quickmenu")),
        "default_answer_type": _strip(row.get("default_answer_type")),
        "default_answer_prompt": _strip(row.get("default_answer_prompt")),
        "notes": _strip(row.get("notes")),
    }


def upsert_rows(session, rows: list[dict[str, Any]], *, chunk_size: int = 50) -> int:
    """PostgreSQL ON CONFLICT DO UPDATE 로 일괄 반영 (created_at 유지, updated_at 갱신)."""
    n = 0
    exclude = {"created_at", "updated_at"}
    cols = [c.key for c in KprintQaQuickmenu.__table__.columns if c.key not in exclude]
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        for data in chunk:
            stmt = pg_insert(KprintQaQuickmenu).values(**data)
            update_cols = {k: getattr(stmt.excluded, k) for k in cols if k != "qna_code"}
            update_cols["updated_at"] = func.now()
            stmt = stmt.on_conflict_do_update(index_elements=["qna_code"], set_=update_cols)
            session.execute(stmt)
            n += 1
    return n


def main() -> None:
    default_csv = os.path.join(PROJECT_ROOT, "docs", "kprint QA bot_초안.csv")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-path", default=default_csv, help="CSV 경로 (기본: docs/kprint QA bot_초안.csv)")
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        help="적재 전 테이블 전체 삭제 (스키마는 유지)",
    )
    parser.add_argument("--dry-run", action="store_true", help="파싱만 하고 DB에 쓰지 않음")
    parser.add_argument("--limit", type=int, default=None, help="테스트용 최대 행 수")
    args = parser.parse_args()

    if not os.path.isfile(args.csv_path):
        raise SystemExit(f"CSV 없음: {args.csv_path}")

    parsed: list[dict[str, Any]] = []
    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "qna_code" not in reader.fieldnames:
            raise SystemExit("CSV 헤더에 qna_code 가 없습니다.")
        for idx, row in enumerate(reader, start=1):
            if args.limit is not None and idx > args.limit:
                break
            try:
                parsed.append(_csv_row_to_db_dict(row))
            except ValueError as e:
                raise SystemExit(f"행 {idx} 파싱 실패: {e}") from e

    print(f"파싱 완료: {len(parsed)} 행 (파일: {args.csv_path})")

    if args.dry_run:
        primaries = sum(1 for r in parsed if r["primary_question"])
        print(f"  primary_question=true: {primaries} 행")
        return

    with SessionLocal() as session:
        if args.truncate_first:
            session.execute(delete(KprintQaQuickmenu))
            session.commit()
            print("kprint_qa_quickmenu 전체 삭제 후 적재")

        n = upsert_rows(session, parsed)
        session.commit()
        print(f"DB 반영(UPSERT) 완료: {n} 행")

        total = session.scalar(select(func.count()).select_from(KprintQaQuickmenu))
        prim = session.scalar(
            select(func.count())
            .select_from(KprintQaQuickmenu)
            .where(KprintQaQuickmenu.primary_question.is_(True))
        )
        print(f"테이블 현재 총 {total} 행, primary_question=true 는 {prim} 행")


if __name__ == "__main__":
    main()
