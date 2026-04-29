"""KPRINT QA 봇 퀵메뉴(카테고리) 행 — CSV ``kprint QA bot_초안.csv`` 구조와 대응.

UI 흐름(데이터 의미):
- ``primary_question`` 가 true 인 행은 메인에서 1차로 노출·탭하는 후보.
- 다음 뎁스는 같은 ``parent_id``·``depth`` 규칙 등으로 앱에서 조합하거나,
  ``follow_question*`` 코드로 연결된 행을 조회하면 된다.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class KprintQaQuickmenu(Base):
    """QA 봇 카테고리/퀵메뉴 한 줄 (qna_code 고유)."""

    __tablename__ = "kprint_qa_quickmenu"

    qna_code: Mapped[str] = mapped_column(Text, primary_key=True)
    primary_question: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quickmenu_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    # CSV 컬럼명 ``user`` (visitor 등) — DB에서는 예약어 회피를 위해 qa_user
    qa_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    subcategory: Mapped[str | None] = mapped_column(Text, nullable=True)
    question_sample: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_sample: Mapped[str | None] = mapped_column(Text, nullable=True)
    links: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_question1: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_question2: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_question3: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_question4: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_question5_formoreinformation: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_quickmenu: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_answer_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_answer_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
