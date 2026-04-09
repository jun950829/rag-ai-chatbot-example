#!/usr/bin/env sh
set -eu

HOST="${APP_HOST:-0.0.0.0}"
PORT="${APP_PORT:-8000}"
RELOAD="${APP_RELOAD:-0}"
RUN_MIGRATIONS="${RUN_MIGRATIONS:-1}"

if [ "$RUN_MIGRATIONS" = "1" ]; then
  alembic upgrade head
fi

if [ "$RELOAD" = "1" ]; then
  exec uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
fi

exec uvicorn app.main:app --host "$HOST" --port "$PORT"
