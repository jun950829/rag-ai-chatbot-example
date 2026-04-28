# `app.rag` — Docker/API 프로세스용 RAG

- **pipeline**: KPRINT(참가업체/전시품) 배치 임베딩, pgvector 테이블 검색, 원격 임베딩 URL(`EMBEDDING_SERVICE_URL`) 지원
- **retrieval**: 의도 분류, 멀티쿼리, RRF, 컷오프
- **search_service**: 검색 엔드포인트에서 쓰는 오케스트레이션

로컬 전용 임베딩 워커는 `embedding/` 디렉터리의 `embed_server` 를 참고하세요.
