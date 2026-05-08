## FAQ 검색 엔진 가이드 (PostgreSQL only)

### 목표
- **FAQ 모드**: PostgreSQL 검색(FTS + pg_trgm + alias + 문자열 rerank)만 사용
- **제품/업체 모드**: 기존 pgvector + embedding + LLM RAG 그대로 유지

### 적용 순서(권장)
- **1) 마이그레이션 적용**: `docs/db/faq_search_migration.sql`
  - `pg_trgm` 확장
  - `faq_alias` 테이블
  - `kprint_qa_quickmenu`의 `normalized_question`, `search_vector`(generated)
  - GIN 인덱스
- **2) alias 적재**: `docs/db/faq_alias_seed_example.sql` 참고 (운영은 CSV + `\copy` 권장)

### 동작 방식(요약)
- **FAQRetriever**가 아래 신호를 점수로 합칩니다.
  - `ts_rank_cd` (websearch_to_tsquery + plainto_tsquery)
  - `pg_trgm similarity()` 및 `%` 연산자(가능하면)
  - alias 매칭(가능하면)
  - 문자열 rerank(SequenceMatcher/token overlap 등)

### 확장/인덱스가 아직 없으면?
애플리케이션은 FAQ 검색 실패 시 **FTS-only 쿼리로 자동 fallback**합니다.  
다만 최고의 성능/정확도를 위해선 `pg_trgm`과 인덱스 적용이 필수입니다.

