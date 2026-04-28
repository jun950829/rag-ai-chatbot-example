"""DB 공통 베이스/타입 정의.

프로덕션 환경에서 ORM 모델을 일관되게 관리하기 위한 모듈.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 SQLAlchemy ORM 모델이 상속하는 Declarative Base."""

