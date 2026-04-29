"""``kprint_qa_quickmenu`` 조회 전용 Repository (비동기).

카테고리 UI:
- ``list_primary_rows``: 메인 1차 버튼 후보 (``primary_question`` = true)
- ``get_row``: 단일 행
- ``list_follow_link_rows``: 한 행의 ``follow_question*`` / ``default_quickmenu`` 에 적힌 ``qna_code`` 순서대로 로드
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.kprint_qa_quickmenu import KprintQaQuickmenu


def _dedupe_codes(codes: list[str | None]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in codes:
        c = (raw or "").strip()
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def follow_codes_from_row(row: KprintQaQuickmenu) -> list[str]:
    """CSV에서 정의한 다음 단계 ``qna_code`` 목록 (순서 유지, 빈 값 제거)."""
    return _dedupe_codes(
        [
            row.follow_question1,
            row.follow_question2,
            row.follow_question3,
            row.follow_question4,
            row.follow_question5_formoreinformation,
            row.default_quickmenu,
        ]
    )


def quickmenu_row_to_dict(row: KprintQaQuickmenu, *, include_prompt: bool = True) -> dict:
    """API 응답용 dict (긴 ``default_answer_prompt`` 는 필요 시 생략)."""
    d: dict = {
        "qna_code": row.qna_code,
        "primary_question": row.primary_question,
        "parent_id": row.parent_id,
        "depth": row.depth,
        "quickmenu_label": row.quickmenu_label,
        "qa_user": row.qa_user,
        "domain": row.domain,
        "category": row.category,
        "subcategory": row.subcategory,
        "question_sample": row.question_sample,
        "answer_sample": row.answer_sample,
        "links": row.links,
        "utm": row.utm,
        "follow_question1": row.follow_question1,
        "follow_question2": row.follow_question2,
        "follow_question3": row.follow_question3,
        "follow_question4": row.follow_question4,
        "follow_question5_formoreinformation": row.follow_question5_formoreinformation,
        "default_quickmenu": row.default_quickmenu,
        "default_answer_type": row.default_answer_type,
        "notes": row.notes,
    }
    if include_prompt:
        d["default_answer_prompt"] = row.default_answer_prompt
    return d


class KprintQaQuickmenuRepository:
    """KPRINT QA 퀵메뉴 테이블 전용."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_primary_rows(
        self,
        *,
        qa_user: str | None = None,
        domain: str | None = None,
    ) -> list[KprintQaQuickmenu]:
        """메인 화면 1차 후보 (``primary_question`` = true). ``qa_user``/``domain`` 으로 필터 가능."""
        stmt = select(KprintQaQuickmenu).where(KprintQaQuickmenu.primary_question.is_(True))
        if qa_user:
            stmt = stmt.where(KprintQaQuickmenu.qa_user == qa_user.strip())
        if domain:
            stmt = stmt.where(KprintQaQuickmenu.domain == domain.strip())
        stmt = stmt.order_by(KprintQaQuickmenu.qna_code)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def list_by_parent_id(self, parent_id: str) -> list[KprintQaQuickmenu]:
        """같은 ``parent_id`` 그룹(예: ko1)으로 묶인 행 — CSV 그룹 탐색용."""
        pid = (parent_id or "").strip()
        stmt = (
            select(KprintQaQuickmenu)
            .where(KprintQaQuickmenu.parent_id == pid)
            .order_by(KprintQaQuickmenu.depth, KprintQaQuickmenu.qna_code)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_row(self, qna_code: str) -> KprintQaQuickmenu | None:
        code = (qna_code or "").strip()
        if not code:
            return None
        stmt = select(KprintQaQuickmenu).where(KprintQaQuickmenu.qna_code == code)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_rows_by_codes_ordered(self, codes: list[str]) -> list[KprintQaQuickmenu]:
        """``qna_code`` IN 조회 후, 요청 순서대로 재정렬."""
        if not codes:
            return []
        stmt = select(KprintQaQuickmenu).where(KprintQaQuickmenu.qna_code.in_(codes))
        res = await self.session.execute(stmt)
        by_code = {r.qna_code: r for r in res.scalars().all()}
        return [by_code[c] for c in codes if c in by_code]

    async def list_follow_link_rows(self, qna_code: str) -> list[KprintQaQuickmenu]:
        """한 항목을 눌렀을 때 CSV에 연결된 다음 단계 행들."""
        row = await self.get_row(qna_code)
        if row is None:
            return []
        ordered = follow_codes_from_row(row)
        return await self.list_rows_by_codes_ordered(ordered)
