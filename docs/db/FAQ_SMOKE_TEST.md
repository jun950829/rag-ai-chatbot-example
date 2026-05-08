## FAQ 검색 스모크 테스트

### 1) FAQ-only 모드가 “절대 RAG/LLM로 내려가지 않는지” 확인

아래 요청은 **FAQ-only**입니다. DB에서 못 찾으면 항상 no-match 안내문이 와야 합니다.

```bash
curl -s -X POST "http://localhost:8000/tools/embedding/api/search" \
  -F "query=없는질문테스트123" \
  -F "model_id=Qwen/Qwen3-Embedding-0.6B" \
  -F "device=cpu" \
  -F "top_k=8" \
  -F "chunk_type=all" \
  -F "answer_mode=template" \
  -F "intent_use_openai=false" \
  -F "faq_only=true" \
  -F "faq_user=visitor"
```

기대:
- `answer_meta.mode`가 `faq_only_no_match` 또는 `faq_no_match`
- **cards/suggestion_cards가 비어있음**
- “제품/업체 관련…” 같은 RAG 안내나 LLM 답변이 절대 나오지 않음

### 2) pg_trgm / alias 미적용 환경에서 FTS fallback 확인

DB에서 `pg_trgm` 또는 `faq_alias`가 없으면, FAQRetriever가 자동으로 **FTS-only**로 fallback 합니다.

기대:
- `answer_meta.trace.fallback == "fts_only"` (매칭이 되는 케이스에서 확인 가능)

### 3) pg_trgm + alias 적용 후 점수(trace) 확인

`docs/db/faq_search_migration.sql` 적용 후, alias를 몇 개 넣고 검색합니다.

기대:
- `answer_meta.trace.db_candidates`가 증가
- `answer_meta.scores`에 `ts_rank`, `trgm_sim`, `alias_match`, `rerank`, `final` 값이 포함

