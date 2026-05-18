# 작업 내용 정리 — 2026-05-14

## 제목: Retrieval/Cards 캐시 + 리스트형 LLM 생략 + Card Detail 캐시

---

## 1. 작업 배경

기존 문제:
- 제품/업체 리스트성 질문에서도 매번 LLM이 긴 설명을 생성한 뒤 카드를 내려줌
- 동일 질문 반복 시 매번 embedding → pgvector → RRF → hydrate → LLM 전체 수행
- 동일 카드 반복 클릭 시 매번 DB 조회 + LLM 호출

개선 목표:
- 리스트 탐색은 짧은 안내 + 카드 캐러셀 중심으로 전환
- 상세 설명은 카드 클릭(`/chat/card-detail`) 에서만 제공
- 반복 질문/클릭에 대한 캐싱으로 응답 속도 향상 + OpenAI 비용 절감

---

## 2. 변경 파일 및 핵심 내용

### 2-1. `app/services/steps/cache.py` — 캐시 유틸 확장

기존 answer 캐시 1종 → 3종 캐시 체계로 확장.

```
기존:
  chat:answer:{sha256}                         TTL 1h     LLM 전체 응답 텍스트

추가:
  chat:retrieval_cards:{sha256}                TTL 6h     {intent, cards[], context, short_answer, language}
  chat:card_detail:{kind}:{ext_id}:{lang}      TTL 24h    카드 상세 LLM 응답 텍스트
```

추가된 함수:

| 함수 | 역할 |
|---|---|
| `get_retrieval_cards_cache(query)` | 정규화된 질문으로 retrieval+cards 캐시 조회 |
| `save_retrieval_cards_cache(query, *, intent, cards, context, short_answer, language)` | 리스트형 응답 결과를 JSON으로 Redis에 저장 |
| `get_card_detail_cache(entity_kind, external_id, language)` | 카드 상세 응답 캐시 조회 |
| `save_card_detail_cache(entity_kind, external_id, language, answer)` | 카드 상세 LLM 응답 저장 |

모든 함수는 Redis 연결 실패 시 graceful fallback (None/no-op).

---

### 2-2. `app/services/steps/intent.py` — 리스트형 응답 판단 함수 추가

파일 하단에 2개 함수 추가:

```python
_LIST_INTENTS = ("product_query", "company_query")
_LIST_MIN_CARDS = 3

def is_list_response(intent: str, cards_count: int) -> bool:
    """검색 의도 + 충분한 카드 → LLM 생략하고 짧은 안내만 반환할지 판단."""
    return intent in _LIST_INTENTS and cards_count >= _LIST_MIN_CARDS

def list_short_answer(intent: str, language: str) -> str:
    """리스트형 응답 시 카드 앞에 보여줄 짧은 안내 메시지."""
```

안내 메시지 예시:

| intent | language | 메시지 |
|---|---|---|
| product_query | ko | 다음과 같은 제품 리스트를 찾았습니다.\n관심 있는 항목을 선택하면 상세 정보를 안내해드릴게요. |
| company_query | ko | 다음과 같은 참가업체 리스트를 찾았습니다.\n관심 있는 업체를 선택하면 상세 정보를 안내해드릴게요. |
| product_query | en | Here are the product results.\nSelect an item to see detailed information. |
| company_query | en | Here are the exhibitor results.\nSelect a company to see detailed information. |

---

### 2-3. `app/services/chat_pipeline.py` — 파이프라인 9단계 → 11단계

기존 흐름:

```
1) normalize → 2) language → 3) answer cache → 4) intent
→ 5) search queries → 6) retrieval → 7) make_cards
→ 8) prompt → LLM → 9) cache save
```

변경 후:

```
 1) normalize
 2) detect_language
 3) answer cache check             ← 기존
 4) intent + early exit            ← 기존
 5) retrieval+cards cache check    ★ 신규
 6) search queries
 7) retrieval (pgvector + RRF)
 8) make_cards + hydrate
 9) list-style → LLM 생략 + 캐시   ★ 신규
10) prompt → LLM streaming
11) answer cache save
```

신규 5단계 (retrieval+cards 캐시 조회):
```python
# 5) retrieval+cards 캐시
async with trace_stage("chat.retrieval_cards_cache"):
    rc_cached = await get_retrieval_cards_cache(normalized)
if rc_cached is not None:
    async def _cached_list() -> AsyncIterator[str]:
        yield rc_cached["short_answer"]
    return rc_cached["cards"], _cached_list()
```

신규 9단계 (리스트형 LLM 생략 + 캐시 저장):
```python
# 9) 리스트형 → LLM 생략, 캐시 저장
if is_list_response(intent, len(cards)):
    short = list_short_answer(intent, language)
    async with trace_stage("chat.retrieval_cards_cache_save"):
        await save_retrieval_cards_cache(
            normalized, intent=intent, cards=cards, context=enriched_ctx,
            short_answer=short, language=language,
        )
    async def _list_answer() -> AsyncIterator[str]:
        yield short
    return cards, _list_answer()
```

---

### 2-4. `app/services/steps/make_cards.py` — Card Detail 캐시

`stream_card_detail` 함수에 캐시 로직 추가:

**캐시 조회** (LLM/DB 조회 이전):
```python
async with trace_stage("chat.card_detail_cache"):
    cached = await get_card_detail_cache(kind or "exhibitor", ext, lang)
if cached is not None:
    async def _cached_detail() -> AsyncIterator[str]:
        yield cached
    return [], _cached_detail()
```

**캐시 저장** (LLM 스트리밍 완료 후, try/finally):
```python
full_text: dict[str, str] = {"v": ""}
try:
    async with trace_stage("chat.card_detail_llm"):
        async for piece in stream_llm_answer(messages=msgs):
            full_text["v"] += piece
            yield piece
finally:
    if full_text["v"]:
        await save_card_detail_cache(kind or "exhibitor", ext, lang, full_text["v"])
```

---

## 3. 캐시 흐름 다이어그램

### 리스트 질문 (예: "UV 프린터 제품 보여줘")

**1회차 (miss)**:
```
normalize → language → answer miss → intent(product_query)
→ retrieval_cards miss → search queries → retrieval → make_cards(8장)
→ is_list_response=True → save retrieval_cards → return short + cards
```
호출: embedding + pgvector + RRF + hydrate (LLM 생략)

**2회차 (hit)**:
```
normalize → language → answer miss → intent(product_query)
→ retrieval_cards HIT → return cached short + cached cards
```
호출: 없음 (Redis GET 1회)

### 일반 질문 (예: "이 전시회 일정 알려줘")

```
normalize → language → answer miss → intent(chat)
→ retrieval_cards miss → search queries → retrieval → make_cards(1장)
→ is_list_response=False → prompt → LLM streaming → answer cache save
```
동작: 기존과 동일 (리스트 조건 미충족 시 LLM 정상 수행)

### 카드 상세 클릭

**1회차**: card_detail miss → DB 조회 → LLM 스트리밍 → card_detail save
**2회차**: card_detail HIT → 즉시 응답 (DB/LLM 전부 스킵)

---

## 4. SSE 응답 포맷 (변경 없음)

모든 경로에서 프론트엔드가 받는 포맷은 동일:

```
event: delta    →  텍스트 (짧은 안내 or LLM 토큰 or 캐시된 텍스트)
event: cards    →  카드 배열 JSON (있을 때만)
event: done     →  "[DONE]"
```

프론트엔드 수정 없이 동작.

---

## 5. 리스트형 판단 정책

| 조건 | 값 |
|---|---|
| intent | `product_query` 또는 `company_query` |
| cards 개수 | >= 3 |
| 두 조건 모두 충족 시 | LLM 생략, 짧은 안내 + 카드만 반환 |
| 미충족 시 | 기존대로 LLM 전체 응답 생성 |

---

## 6. 기대 효과

| 항목 | Before | After |
|---|---|---|
| 리스트 질문 latency | embedding + 검색 + hydrate + LLM (~3-5s) | 짧은 안내 즉시 (~200ms, 캐시 시 ~50ms) |
| 동일 질문 반복 | 매번 전체 파이프라인 | retrieval_cards 캐시 hit (~50ms) |
| 카드 반복 클릭 | 매번 DB + LLM | card_detail 캐시 hit (~50ms) |
| OpenAI 비용 | 리스트 질문마다 LLM 호출 | 리스트 질문은 LLM 미호출 |
| hallucination | LLM이 검색 결과 외 내용 생성 가능 | 리스트에서는 사실만 전달, 상세는 card-detail로 집중 |

---

## 7. 주의사항

- 리스트형 LLM 생략은 카드 3개 이상 + product_query/company_query 조건에서만 적용
- `chat` intent나 카드 2개 이하면 기존대로 LLM 전체 답변 생성
- 캐시 키는 정규화된 질문 기반 → 동일 의미의 표현 차이는 정규화 단계에서 흡수
- card_detail 캐시 키는 `{entity_kind}:{external_id}:{language}` → 한/영 별도 캐시
- Redis 장애 시 모든 캐시 함수는 miss 처리로 fallback → 기존 흐름으로 정상 동작
- 기존 answer 캐시(TTL 1h)는 LLM 전체 응답용으로 그대로 유지
