#!/usr/bin/env bash
# 로컬 레포 → 메인 EC2(api) + 임베딩 EC2(worker) 코드 반영 및 재시작.
#
# 사용:
#   ./scripts/deploy_ec2_all.sh
#   REMOTE_MAIN=user@host REMOTE_EMBED=user@host2 SSH_IDENTITY=~/.ssh/key.pem ./scripts/deploy_ec2_all.sh
#
# 이 스크립트는 기본적으로 **아무것도 생략하지 않고** 배포한다.
# - new_main frontend_old_version npm build 수행
# - main(api) 반영
# - embedding(worker) 반영
#
# 이미지 전체 재빌드(느리지만 확실):
#   REBUILD_MAIN=1 ./scripts/deploy_ec2_all.sh
#   REBUILD_EMBED=1 ./scripts/deploy_ec2_all.sh
#
# 기본은 코드 rsync + 컨테이너/프로세스 재시작만 수행(pip install 없음).
#
# Permission denied (publickey): kprint_ingest_ec2_main.sh 와 동일하게
# 레포 루트의 exmatch-publickey.pem 을 기본 -i 로 사용(있을 때).
set -euo pipefail

REMOTE_MAIN="${REMOTE_MAIN:-exmatch2604@52.64.112.27}"
REMOTE_EMBED="${REMOTE_EMBED:-exmatch2604@15.135.211.14}"
REPO_ROOT="${REPO_ROOT:-rag-ai-chatbot-example}"
REPO_ROOT="${REPO_ROOT%/}"
REBUILD_MAIN="${REBUILD_MAIN:-0}"
REBUILD_EMBED="${REBUILD_EMBED:-0}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -z "${SSH_IDENTITY:-}" && -f "$ROOT/exmatch-publickey.pem" ]]; then
  SSH_IDENTITY="$ROOT/exmatch-publickey.pem"
fi
if [[ -n "${SSH_IDENTITY:-}" ]]; then
  case "$SSH_IDENTITY" in
    "~") SSH_IDENTITY="$HOME" ;;
    "~"/*) SSH_IDENTITY="$HOME/${SSH_IDENTITY#~/}" ;;
  esac
fi

ssh_rsh() {
  local -a a=(ssh -o BatchMode=yes)
  if [[ -n "${SSH_IDENTITY:-}" ]]; then
    [[ -r "$SSH_IDENTITY" ]] || {
      echo "오류: SSH_IDENTITY 를 읽을 수 없습니다: $SSH_IDENTITY" >&2
      exit 1
    }
    a+=(-o IdentitiesOnly=yes -i "$SSH_IDENTITY")
  fi
  printf '%q ' "${a[@]}"
}

SSH_CMD=(ssh -o BatchMode=yes)
if [[ -n "${SSH_IDENTITY:-}" ]]; then
  [[ -r "$SSH_IDENTITY" ]] || {
    echo "오류: SSH_IDENTITY 를 읽을 수 없습니다: $SSH_IDENTITY" >&2
    exit 1
  }
  SSH_CMD+=(-o IdentitiesOnly=yes -i "$SSH_IDENTITY")
fi

RSYNC_RSH="$(ssh_rsh)"

rsync_common_excludes=(
  --exclude '__pycache__/'
  --exclude '*.pyc'
  --exclude '.pytest_cache/'
  --exclude '.mypy_cache/'
  --exclude '.venv/'
  --exclude 'venv/'
)
# 원격 .env 유지
rsync_env_exclude=(--exclude '.env')

build_chatbot_frontend() {
  if [[ ! -f "$ROOT/new_main/frontend_old_version/package.json" ]]; then
    return 0
  fi
  if ! command -v npm >/dev/null 2>&1; then
    echo "오류: npm 이 없어 new_main 프론트 빌드를 수행할 수 없습니다. Node/npm 설치 후 다시 실행하세요." >&2
    exit 1
  fi
  echo "==> build new_main frontend: frontend_old_version (→ new_main/frontend_old_version/dist)"
  (cd "$ROOT/new_main/frontend_old_version" && npm ci && npm run build)
}

deploy_main() {
  build_chatbot_frontend

  local remote="$REMOTE_MAIN"
  echo "==> ensure remote dir: $remote:$REPO_ROOT/new_main/"
  "${SSH_CMD[@]}" "$remote" bash -s "$REPO_ROOT" <<'REMOTE_DIR'
set -euo pipefail
REPO_ROOT="${1:-rag-ai-chatbot-example}"
if [[ "$REPO_ROOT" != /* ]]; then REPO_ROOT="$HOME/$REPO_ROOT"; fi
mkdir -p "$REPO_ROOT/new_main"
REMOTE_DIR
  echo "==> rsync new_main/ → $remote:$REPO_ROOT/new_main/"
  # rsync 원격 상대경로(선행 슬래시 없음) = 해당 호스트 사용자 홈 기준 (kprint_ingest_ec2_main 과 동일)
  rsync -avz -e "$RSYNC_RSH" \
    "${rsync_common_excludes[@]}" "${rsync_env_exclude[@]}" \
    --exclude 'frontend/node_modules/' \
    --exclude 'frontend/.next/' \
    --exclude 'frontend_old_version/node_modules/' \
    "$ROOT/new_main/" "$remote:$REPO_ROOT/new_main/"

  echo "==> remote main: new_main api 컨테이너 반영 + 재시작 ($remote)"
  "${SSH_CMD[@]}" "$remote" bash -s "$REPO_ROOT" "$REBUILD_MAIN" <<'REMOTE_MAIN'
set -euo pipefail
REPO_ROOT="${1:-rag-ai-chatbot-example}"
REBUILD="${2:-0}"
if [[ "$REPO_ROOT" != /* ]]; then REPO_ROOT="$HOME/$REPO_ROOT"; fi

if [[ "$REBUILD" == "1" ]]; then
  cd "$REPO_ROOT/new_main" || { echo "오류: $REPO_ROOT/new_main 없음" >&2; exit 1; }
  docker compose -f docker-compose.ec2-1.yml build api
  docker compose -f docker-compose.ec2-1.yml up -d api
  echo "new_main: compose build+up api 완료"
  exit 0
fi

# compose 스택의 api만 쓰면 REDIS_URL=redis://redis / POSTGRES_DSN=...@postgres 가 DNS로 풀린다.
# publish=8000 만 보면 compose 밖에서 띄운 다른 컨테이너를 집을 수 있어 redis/postgres 이름 해석이 실패한다.
COMPOSE_DIR="$REPO_ROOT/new_main"
CID=""
if [[ -f "$COMPOSE_DIR/docker-compose.ec2-1.yml" ]]; then
  CID="$(cd "$COMPOSE_DIR" && docker compose -f docker-compose.ec2-1.yml ps -q api 2>/dev/null | head -n1 || true)"
fi
if [[ -z "${CID:-}" ]]; then
  CID="$(docker ps -q --filter publish=8000 | head -n1 || true)"
fi
if [[ -z "${CID:-}" ]]; then
  echo "오류: new_main compose 의 api 컨테이너를 찾지 못했습니다. $COMPOSE_DIR 에서 docker compose -f docker-compose.ec2-1.yml up -d 또는 REBUILD_MAIN=1 로 기동하세요." >&2
  exit 1
fi
echo "Using api container: $CID"
# /srv/main/app 가 이미 있으면 ``docker cp .../app DEST`` 는 DEST/app/ 하위에 또 app 이 생겨
# 런타임은 /srv/main/app/... 를 쓰므로 반드시 디렉터리 *내용*을 덮어쓴다.
docker cp "$REPO_ROOT/new_main/app/." "$CID:/srv/main/app/"
# 프론트 dist도 함께 갱신 (frontend_old_version/dist → 컨테이너 /srv/main/frontend/dist)
if [[ -d "$REPO_ROOT/new_main/frontend_old_version/dist" ]]; then
  docker cp "$REPO_ROOT/new_main/frontend_old_version/dist/." "$CID:/srv/main/frontend/dist/"
fi
docker restart "$CID"
echo "new_main: docker cp app(+dist) + restart 완료 ($CID)"
REMOTE_MAIN
}

deploy_embed() {
  local remote="$REMOTE_EMBED"
  echo "==> ensure remote dir: $remote:$REPO_ROOT/embedding/"
  "${SSH_CMD[@]}" "$remote" bash -s "$REPO_ROOT" <<'REMOTE_DIR'
set -euo pipefail
REPO_ROOT="${1:-rag-ai-chatbot-example}"
if [[ "$REPO_ROOT" != /* ]]; then REPO_ROOT="$HOME/$REPO_ROOT"; fi
mkdir -p "$REPO_ROOT/embedding"
REMOTE_DIR
  echo "==> rsync embedding/ → $remote:$REPO_ROOT/embedding/"
  rsync -avz -e "$RSYNC_RSH" \
    "${rsync_common_excludes[@]}" "${rsync_env_exclude[@]}" \
    "$ROOT/embedding/" "$remote:$REPO_ROOT/embedding/"

  echo "==> remote embedding: worker 반영 + 재시작 ($remote)"
  "${SSH_CMD[@]}" "$remote" bash -s "$REPO_ROOT" "$REBUILD_EMBED" <<'REMOTE_EMBED'
set -euo pipefail
REPO_ROOT="${1:-rag-ai-chatbot-example}"
REBUILD="${2:-0}"
if [[ "$REPO_ROOT" != /* ]]; then REPO_ROOT="$HOME/$REPO_ROOT"; fi
EDIR="$REPO_ROOT/embedding"

if [[ "$REBUILD" == "1" ]]; then
  cd "$EDIR" || { echo "오류: $EDIR 없음" >&2; exit 1; }
  docker compose -f docker-compose.ec2-2.yml build worker
  docker compose -f docker-compose.ec2-2.yml up -d worker
  echo "embedding: compose build+up worker 완료"
  exit 0
fi

CID=""
if [[ -f "$EDIR/docker-compose.ec2-2.yml" ]]; then
  CID="$(cd "$EDIR" && docker compose -f docker-compose.ec2-2.yml ps -q worker 2>/dev/null | head -n1 || true)"
fi
if [[ -z "${CID:-}" ]]; then
  CID="$(docker ps -qf "name=embedding" | head -n1 || true)"
fi
if [[ -z "${CID:-}" ]]; then
  CID="$(docker ps -qf "name=worker" | head -n1 || true)"
fi

if [[ -n "${CID:-}" ]]; then
  # docker cp SRC DEST — DEST 가 디렉터리면 SRC 베이스네임이 한 단계 중첩될 수 있음 → worker/. 사용
  docker cp "$EDIR/worker/." "$CID:/srv/embedding/worker/"
  docker restart "$CID"
  echo "embedding: docker cp worker + restart 완료 ($CID)"
  exit 0
fi

echo "embedding: compose worker 컨테이너 없음 → 호스트에서 nohup worker 재시도 ($EDIR)"
cd "$EDIR" || { echo "오류: embedding 디렉터리 없음" >&2; exit 1; }
if [[ -f .venv/pyvenv.cfg ]] && grep -q '/Users/' .venv/pyvenv.cfg 2>/dev/null; then
  echo "경고: .venv 설정에 macOS 경로(/Users/)가 보입니다 — 배포 스크립트는 pip 로 고치지 않습니다. 필요 시 서버에서 직접 venv 정리를 하세요." >&2
fi
PY=python3
if [[ -x .venv/bin/python ]]; then PY=".venv/bin/python"; elif [[ -x venv/bin/python ]]; then PY="venv/bin/python"; fi
pkill -f '[p]ython -m worker.main' 2>/dev/null || true
sleep 1
nohup "$PY" -m worker.main >> "$EDIR/worker.log" 2>&1 &
echo "embedding: nohup worker 재기동 pid=$! log=$EDIR/worker.log python=$PY"
REMOTE_EMBED
}

deploy_main
deploy_embed

echo "배포 스크립트 종료 OK."
