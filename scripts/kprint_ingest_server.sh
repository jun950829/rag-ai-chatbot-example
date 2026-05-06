#!/usr/bin/env bash
# main 배포 호스트에서 실행: ~/rag-ai-chatbot-example(기본) 아래 data, docs, scripts 를 api 컨테이너로 넣고 ingest.
#
# 디렉터리 준비(최초 1회):
#   mkdir -p ~/rag-ai-chatbot-example/{data,docs,scripts}
#
# 이후 data/*.csv, docs/*.csv, scripts/*.py 를 이 경로에 두고:
#   bash ~/rag-ai-chatbot-example/scripts/kprint_ingest_server.sh
# 다른 경로면: REPO_ROOT=/path/to/rag-ai-chatbot-example bash ...
#
# DB 연결은 api 컨테이너 안의 설정(DATABASE_URL)을 그대로 쓴다.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/rag-ai-chatbot-example}"
REPO_ROOT="${REPO_ROOT%/}"

if [[ ! -d "$REPO_ROOT/data" || ! -d "$REPO_ROOT/docs" || ! -d "$REPO_ROOT/scripts" ]]; then
  echo "오류: $REPO_ROOT 에 data/, docs/, scripts/ 가 필요합니다." >&2
  exit 1
fi

for f in \
  KPRINT_ExhibitorsExport_2025.csv \
  KPRINT_ExhibitItemsExport_2025.csv; do
  [[ -f "$REPO_ROOT/data/$f" ]] || {
    echo "오류: $REPO_ROOT/data/$f 가 없습니다." >&2
    exit 1
  }
done

QA_CSV="$REPO_ROOT/docs/kprint QA bot_초안.csv"
if [[ ! -f "$QA_CSV" ]]; then
  echo "오류: QA CSV 없음: $QA_CSV" >&2
  exit 1
fi

CID="$(docker ps -q --filter publish=8000 | head -n1)"
if [[ -z "${CID:-}" ]]; then
  echo "오류: publish=8000 인 컨테이너가 없습니다. docker ps 로 확인하세요." >&2
  exit 1
fi
echo "Using container: $CID  (REPO_ROOT=$REPO_ROOT)"

docker exec "$CID" bash -c 'rm -rf /tmp/repo && mkdir -p /tmp/repo && ln -sf /srv/main /tmp/repo/main'

docker cp "$REPO_ROOT/data" "$CID:/tmp/repo/"
docker cp "$REPO_ROOT/docs" "$CID:/tmp/repo/"
docker cp "$REPO_ROOT/scripts" "$CID:/tmp/repo/"

docker exec -w /tmp/repo "$CID" python scripts/ingest_koba_exhibitors_2026.py \
  --path /tmp/repo/data/KPRINT_ExhibitorsExport_2025.csv
docker exec -w /tmp/repo "$CID" python scripts/ingest_koba_exhibit_items_2026.py \
  --path /tmp/repo/data/KPRINT_ExhibitItemsExport_2025.csv
docker exec -w /tmp/repo "$CID" python scripts/load_kprint_qa_quickmenu.py \
  --csv-path "/tmp/repo/docs/kprint QA bot_초안.csv"

echo "ingest 완료 (REPO_ROOT=$REPO_ROOT)."
