#!/usr/bin/env bash
# 로컬 Postgres의 KPRINT Qwen3 임베딩(및 선택 시 카탈로그)을 원격 DB로 복사한다.
#
# 왜 두 단계가 있나:
#   - 임베딩 행의 entity_id 는 kprint_exhibitor / kprint_exhibit_item 의 id(UUID) 를 FK 로 묶는다.
#     로컬과 원격에서 따로 CSV ingest 만 했으면 UUID 가 달라 임베딩만 넣으면 FK 오류가 난다.
#   - 그때 SYNC_CATALOG=1 로 참가업체·전시품 두 테이블까지 로컬 기준으로 덮어쓴 뒤 임베딩을 넣는다.
#
# PG 16 서버 + PG 17 클라이언트(pg_dump) 일 때 custom 덤프의 SET transaction_timeout 때문에
# pg_restore 가 실패할 수 있어, plain SQL 덤프를 sed 로 한 줄 건너뛴 뒤 psql 에 넣는다.
#
# 사용:
#   SRC=postgresql://postgres:postgres@127.0.0.1:5432/rag_template \
#   DST=postgresql://postgres:postgres@52.64.112.27:5432/chatbot \
#   TRUNCATE_FIRST=1 SYNC_CATALOG=1 \
#   ./scripts/sync_kprint_qwen3_embeddings.sh
#
# 임베딩만(원격 id 가 로컬과 이미 같은 경우만):
#   TRUNCATE_FIRST=1 SYNC_CATALOG=0 ./scripts/sync_kprint_qwen3_embeddings.sh  # SYNC_CATALOG 생략과 동일
set -euo pipefail

_ensure_pg_clients_in_path() {
  if command -v pg_dump >/dev/null 2>&1 && command -v psql >/dev/null 2>&1; then
    return 0
  fi
  local d
  for d in \
    "/opt/homebrew/opt/libpq/bin" \
    "/usr/local/opt/libpq/bin" \
    "/opt/homebrew/opt/postgresql@16/bin" \
    "/usr/local/opt/postgresql@16/bin" \
    "/opt/homebrew/opt/postgresql@15/bin" \
    "/usr/local/opt/postgresql@15/bin"; do
    if [[ -x "${d}/pg_dump" ]]; then
      PATH="${d}:${PATH}"
      export PATH
      return 0
    fi
  done
  echo "PostgreSQL 클라이언트(pg_dump, psql)를 찾지 못했습니다. brew install libpq 권장." >&2
  exit 1
}

_filter_pg_plain_for_pg16() {
  # PG17+ pg_dump 가 넣는 서버에 없는 GUC 제거
  sed -e '/^[[:space:]]*SET[[:space:]]*transaction_timeout/d' \
    -e '/^[[:space:]]*SET[[:space:]]*idle_in_transaction_session_timeout/d'
}

_data_dump_to_dst() {
  local label="$1"
  shift
  echo "==> pg_dump (plain) $label -> 원격 psql"
  # shellcheck disable=SC2068
  pg_dump "$SRC" --format=p --data-only --no-owner --no-acl "$@" | _filter_pg_plain_for_pg16 | psql "$DST" -v ON_ERROR_STOP=1
}

_ensure_pg_clients_in_path

SRC="${SRC:-postgresql://postgres:postgres@127.0.0.1:5432/rag_template}"
DST="${DST:-postgresql://postgres:postgres@52.64.112.27:5432/chatbot}"
TRUNCATE_FIRST="${TRUNCATE_FIRST:-0}"
SYNC_CATALOG="${SYNC_CATALOG:-0}"

EMB_TABLES=(
  kprint_exhibit_item_evidence_embedding_qwen3_0_6b_eng
  kprint_exhibit_item_evidence_embedding_qwen3_0_6b_kor
  kprint_exhibit_item_profile_embedding_qwen3_0_6b_eng
  kprint_exhibit_item_profile_embedding_qwen3_0_6b_kor
  kprint_exhibitor_evidence_embedding_qwen3_0_6b_eng
  kprint_exhibitor_evidence_embedding_qwen3_0_6b_kor
  kprint_exhibitor_profile_embedding_qwen3_0_6b_eng
  kprint_exhibitor_profile_embedding_qwen3_0_6b_kor
)

if [[ "$SYNC_CATALOG" == "1" && "$TRUNCATE_FIRST" != "1" ]]; then
  echo "SYNC_CATALOG=1 은 원격 kprint_exhibitor / kprint_exhibit_item 을 비우고 덮어써야 하므로 TRUNCATE_FIRST=1 과 함께 쓰세요." >&2
  exit 1
fi

if [[ "$TRUNCATE_FIRST" == "1" ]]; then
  # FK 가 있으므로 한 번의 TRUNCATE 에 테이블을 모두 나열해야 한다 (개별 TRUNCATE 순서로는 자식이 남아 실패할 수 있음).
  tables_csv=""
  sep=""
  for t in "${EMB_TABLES[@]}"; do
    tables_csv+="${sep}public.${t}"
    sep=", "
  done
  if [[ "$SYNC_CATALOG" == "1" ]]; then
    tables_csv+="${sep}public.kprint_exhibit_item, public.kprint_exhibitor"
  fi
  echo "==> 원격 TRUNCATE (단일 구문)"
  psql "$DST" -v ON_ERROR_STOP=1 -c "TRUNCATE TABLE ${tables_csv};"
fi

if [[ "$SYNC_CATALOG" == "1" ]]; then
  _data_dump_to_dst "kprint_exhibitor" -t "public.kprint_exhibitor"
  _data_dump_to_dst "kprint_exhibit_item" -t "public.kprint_exhibit_item"
fi

emb_args=()
for t in "${EMB_TABLES[@]}"; do
  emb_args+=(-t "public.${t}")
done
_data_dump_to_dst "8x embedding" "${emb_args[@]}"

echo "==> 완료."
