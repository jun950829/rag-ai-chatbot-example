#!/usr/bin/env bash
# main 스택(EC2) Postgres에 KPRINT CSV + QA CSV 적재.
#
# 사용 예:
#   ./scripts/kprint_ingest_ec2_main.sh
#   REMOTE=exmatch2604@52.64.112.27 SSH_IDENTITY=~/.ssh/other.pem ./scripts/kprint_ingest_ec2_main.sh
#
# Permission denied (publickey) 일 때:
#   - 레포 루트의 exmatch-publickey.pem 이 있으면 기본으로 -i 에 사용한다(파일 내용은 OpenSSH 개인키).
#   - 다른 키면 SSH_IDENTITY=개인키경로
#   - 키 권한: chmod 600 개인키
#   - ssh -v $REMOTE 로 어떤 키를 시도하는지 확인
#   - ssh-add -l / ssh-add ~/.ssh/... 로 에이전트에 올리거나, 위처럼 SSH_IDENTITY 로 지정
#
# 사전: ssh $REMOTE 접속 가능, 원격에서 docker 로 api 컨테이너 실행 중.
# 원격 경로 REPO_ROOT: 기본 rag-ai-chatbot-example (= ~/rag-ai-chatbot-example). 절대경로도 가능.
set -euo pipefail

REMOTE="${REMOTE:-exmatch2604@52.64.112.27}"
REPO_ROOT="${REPO_ROOT:-rag-ai-chatbot-example}"
REPO_ROOT="${REPO_ROOT%/}"
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
  # rsync -e 용 한 줄 명령 (경로에 공백 있어도 %q 로 이스케이프)
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

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/data" "$STAGE/docs" "$STAGE/scripts"
cp "$ROOT/data/KPRINT_ExhibitorsExport_2025.csv" "$STAGE/data/"
cp "$ROOT/data/KPRINT_ExhibitItemsExport_2025.csv" "$STAGE/data/"
cp "$ROOT/docs/kprint QA bot_초안.csv" "$STAGE/docs/"
for f in \
  ingest_db_env.py \
  ingest_koba_exhibitors_2026.py \
  ingest_koba_exhibit_items_2026.py \
  ingest_kprint_exhibitors_2026.py \
  ingest_kprint_exhibit_items_2026.py \
  load_kprint_qa_quickmenu.py \
  kprint_ingest_server.sh \
  kprint_ingest_ec2_main.sh; do
  cp "$ROOT/scripts/$f" "$STAGE/scripts/"
done

echo "==> rsync → $REMOTE:$REPO_ROOT/"
RSYNC_RSH_CMD="$(ssh_rsh)"
rsync -avz -e "$RSYNC_RSH_CMD" "$STAGE/" "$REMOTE:$REPO_ROOT/"

echo "==> remote: kprint_ingest_server.sh (REPO_ROOT=$REPO_ROOT)"
if [[ "$REPO_ROOT" = /* ]]; then
  "${SSH_CMD[@]}" "$REMOTE" "REPO_ROOT=\"$REPO_ROOT\" bash \"$REPO_ROOT/scripts/kprint_ingest_server.sh\""
else
  "${SSH_CMD[@]}" "$REMOTE" "REPO_ROOT=\"\$HOME/$REPO_ROOT\" bash \"\$HOME/$REPO_ROOT/scripts/kprint_ingest_server.sh\""
fi

echo "로컬 스크립트 종료 OK."
