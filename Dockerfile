FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/main

WORKDIR /app

COPY requirements-api.txt pyproject.toml README.md ./
# 앱 코드 변경(신규 모듈 등) 후에는 반드시 `docker compose build api` 로 이미지 재빌드
COPY main/app ./main/app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY docker ./docker
COPY scripts ./scripts

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-api.txt

EXPOSE 8000

CMD ["./docker/entrypoint.sh"]
