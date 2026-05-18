#!/usr/bin/env bash
# 새 Next.js 프론트엔드만 EC2에 배포한다.
# 기존 old_version 프론트(8000번 FastAPI에 마운트)는 그대로 유지.
# 새 프론트는 포트 3001에서 독립 실행.
#
# 사용:
#   ./scripts/deploy_ec2_new_front.sh
#
# 접속: http://<REMOTE_MAIN_IP>:3001
set -euo pipefail

REMOTE_MAIN="${REMOTE_MAIN:-exmatch2604@52.64.112.27}"
REMOTE_IP="${REMOTE_IP:-52.64.112.27}"
API_PORT="${API_PORT:-8000}"
FRONT_PORT="${FRONT_PORT:-3001}"
REPO_ROOT="${REPO_ROOT:-rag-ai-chatbot-example}"
REPO_ROOT="${REPO_ROOT%/}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FE_DIR="$ROOT/new_main/frontend"

if [[ -z "${SSH_IDENTITY:-}" && -f "$ROOT/exmatch-publickey.pem" ]]; then
  SSH_IDENTITY="$ROOT/exmatch-publickey.pem"
fi
if [[ -n "${SSH_IDENTITY:-}" ]]; then
  case "$SSH_IDENTITY" in
    "~") SSH_IDENTITY="$HOME" ;;
    "~"/*) SSH_IDENTITY="$HOME/${SSH_IDENTITY#~/}" ;;
  esac
fi

SSH_CMD=(ssh -o BatchMode=yes)
if [[ -n "${SSH_IDENTITY:-}" ]]; then
  [[ -r "$SSH_IDENTITY" ]] || {
    echo "오류: SSH_IDENTITY 를 읽을 수 없습니다: $SSH_IDENTITY" >&2
    exit 1
  }
  SSH_CMD+=(-o IdentitiesOnly=yes -i "$SSH_IDENTITY")
fi

ssh_rsh() {
  local -a a=(ssh -o BatchMode=yes)
  if [[ -n "${SSH_IDENTITY:-}" ]]; then
    a+=(-o IdentitiesOnly=yes -i "$SSH_IDENTITY")
  fi
  printf '%q ' "${a[@]}"
}
RSYNC_RSH="$(ssh_rsh)"

# ── 1) 로컬에서 Next.js standalone 빌드 ──
echo "==> [local] Next.js standalone 빌드 (NEXT_PUBLIC_API_ENDPOINT=http://${REMOTE_IP}:${API_PORT})"
if ! command -v npm >/dev/null 2>&1; then
  echo "오류: npm 이 없습니다." >&2; exit 1
fi
(
  cd "$FE_DIR"
  npm ci --silent 2>/dev/null || npm install --silent
  NEXT_PUBLIC_API_ENDPOINT="http://${REMOTE_IP}:${API_PORT}" npx next build
)

# standalone 빌드 결과 확인
if [[ ! -f "$FE_DIR/.next/standalone/server.js" ]]; then
  echo "오류: standalone 빌드 결과 없음 ($FE_DIR/.next/standalone/server.js)" >&2
  exit 1
fi
echo "==> [local] 빌드 완료"

# ── 2) 빌드 결과를 EC2에 rsync ──
REMOTE_DEST="$REPO_ROOT/new_main/frontend_next"

echo "==> ensure remote dir: $REMOTE_MAIN:$REMOTE_DEST"
"${SSH_CMD[@]}" "$REMOTE_MAIN" "mkdir -p ~/$REMOTE_DEST"

echo "==> rsync standalone → $REMOTE_MAIN:$REMOTE_DEST/"
rsync -az --delete -e "$RSYNC_RSH" \
  "$FE_DIR/.next/standalone/" "$REMOTE_MAIN:$REMOTE_DEST/"

echo "==> rsync static assets"
rsync -az -e "$RSYNC_RSH" \
  "$FE_DIR/.next/static/" "$REMOTE_MAIN:$REMOTE_DEST/.next/static/"

echo "==> rsync public/"
rsync -az -e "$RSYNC_RSH" \
  "$FE_DIR/public/" "$REMOTE_MAIN:$REMOTE_DEST/public/"

# ── 3) EC2에서 기존 프로세스 종료 + 새로 실행 ──
echo "==> [remote] 포트 ${FRONT_PORT}에서 Next.js 기동"
"${SSH_CMD[@]}" "$REMOTE_MAIN" bash -s "$REMOTE_DEST" "$FRONT_PORT" <<'REMOTE_RUN'
set -euo pipefail
DEST="${1}"
PORT="${2}"
if [[ "$DEST" != /* ]]; then DEST="$HOME/$DEST"; fi

# 기존 프로세스 종료
if fuser "$PORT/tcp" >/dev/null 2>&1; then
  echo "포트 $PORT 사용 중인 프로세스 종료"
  fuser -k "$PORT/tcp" 2>/dev/null || true
  sleep 2
fi

cd "$DEST"
LOG="$DEST/next.log"

HOSTNAME=0.0.0.0 PORT="$PORT" nohup node server.js >> "$LOG" 2>&1 &
PID=$!
sleep 2

if kill -0 "$PID" 2>/dev/null; then
  echo "Next.js 기동 성공: pid=$PID port=$PORT log=$LOG"
else
  echo "오류: Next.js 기동 실패. 로그 확인: $LOG" >&2
  tail -20 "$LOG" 2>/dev/null
  exit 1
fi
REMOTE_RUN

echo ""
echo "============================================"
echo "  새 프론트엔드 접속 주소:"
echo "  http://${REMOTE_IP}:${FRONT_PORT}"
echo ""
echo "  기존 프론트(old_version):"
echo "  http://${REMOTE_IP}:${API_PORT}"
echo "============================================"
echo ""
echo "deploy_ec2_new_front.sh 완료 OK."
