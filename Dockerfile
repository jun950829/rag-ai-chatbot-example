FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/main

WORKDIR /app

COPY requirements-api.txt pyproject.toml README.md ./
COPY main/app ./main/app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY docker ./docker

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements-api.txt

EXPOSE 8000

CMD ["./docker/entrypoint.sh"]
