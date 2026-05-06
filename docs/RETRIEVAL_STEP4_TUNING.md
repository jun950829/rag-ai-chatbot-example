# Retrieval Step 4 Tuning Guide

이 문서는 `retrieval_step_4(의미 검색)` 지연을 줄이기 위한 제안과, 현재 저장소에 적용한 기본 튜닝값을 정리한다.

## 1) 병목 해석

- `retrieval_step_4`는 보통 아래 비용의 합이다.
  - 다중 쿼리 임베딩 생성
  - profile/evidence 벡터 검색(SQL)
  - 쿼리별 결과 병합/정규화
- 총 시간은 대략 `쿼리 개수 × 쿼리당 비용`에 비례한다. 임베딩은 `embed_queries_text`로 **한 번에 배치**하고, DB 검색만 쿼리별로 `ThreadPoolExecutor`에 태운다.
- `search_embedding_tables`의 브랜치별 `LIMIT` 기본값은 `min(max(top_k×5, 14), 36)`으로 잡혀 있다 (과거 `max(top_k, 50)`보다 가볍다). recall 이슈가 있으면 `per_table_limit`를 올리는 쪽으로 조정한다.

## 2) 제안 (속도 우선)

- **쿼리 개수 축소**: 기본값 `min_queries=max_queries=2`
- **쿼리당 후보 수 축소**: `top_k_per_query=4`
- **evidence 비율 축소**: `evidence_ratio=0.45`
- **컷오프 강화**: `score_cutoff=0.25`
- **컨텍스트 길이 축소**: `context_limit=4`
- **최종 top_k 축소**: worker의 `retrieval_top_k=6`

## 3) 이번에 적용한 값

### API 기본값 (`main/app/core/config.py`)

- `retrieval_min_queries = 2`
- `retrieval_max_queries = 2`
- `retrieval_top_k_per_query = 4`
- `retrieval_evidence_ratio = 0.45`
- `retrieval_score_cutoff = 0.25`
- `retrieval_context_limit = 4`

### Worker 기본값 (`embedding/worker/config.py`)

- `retrieval_top_k = 6`
- `retrieval_min_queries = 2`
- `retrieval_max_queries = 2`
- `retrieval_top_k_per_query = 4`
- `retrieval_evidence_ratio = 0.45`
- `retrieval_score_cutoff = 0.25`
- `retrieval_context_limit = 4`
- `retrieval_intent_use_openai = False` (의도 분류 OpenAI 비활성)

## 4) 운영 체크포인트

- 변경 후 `chatbot` UI의 "단계별 소요시간"에서 `retrieval_step_4` ms를 먼저 확인한다.
- 품질 저하가 보이면 순서대로 되돌린다.
  1. `top_k_per_query` 4 -> 6
  2. `retrieval_top_k` 6 -> 8
  3. `evidence_ratio` 0.45 -> 0.60
  4. `context_limit` 4 -> 6

## 5) 다음 후보 (구조 개선)

- ~~쿼리별 임베딩/검색 병렬화~~ → `semantic_search_multi_query`에서 `ThreadPoolExecutor` 적용됨 (`main/app/rag/retrieval/search.py`).
- 질의 임베딩 캐시
- pgvector 인덱스/파라미터 튜닝
