# 챗봇·RAG·퀵메뉴 아키텍처

이 문서는 **현재 이 저장소에서 “챗봇”이 동작하는 경로**를 한곳에 정리한다.  
(이름은 챗봇이지만, 실제로는 **Redis 큐형 스트리밍 챗**, **동기 RAG 검색 UI**, **저장형 FAQ 카테고리 UI(Test_AI, /tools/chatbot 내 통합)** 가 있다.)

---

## 1. 전체 그림

```mermaid
flowchart TB
  subgraph ui["브라우저 / 클라이언트"]
    T0["chatbot.html\n/tools/chatbot (카테고리+채팅)"]
    T1["embedding_tool.html\n/tools/embedding"]
    T2["chatbot.html\n/tools/chatbot"]
    T3["chatbot_queue + SSE"]
  end

  subgraph api["FastAPI (main/app/main.py)"]
    E["embedding_tool 라우터\n/tools/..."]
    C["chatbot 라우터\n/chat, /stream/..."]
    R["api_router\n/api/v1/..."]
  end

  subgraph rag["RAG (동기, API 프로세스)"]
    SS["search_service.run_vector_search"]
    RP["retrieval.execute_retrieval_pipeline"]
    PL["pipeline: embed_query_text\nsearch_embedding_tables"]
  end

  subgraph data["데이터"]
    PG[(PostgreSQL)]
    RD[(Redis)]
  end

  subgraph worker["별도 프로세스 (선택)"]
    LLM["LLM 워커\nRedis 큐 소비"]
    EMB["임베딩 서버\nEMBEDDING_SERVICE_URL"]
  end

  T0 --> E
  T1 --> E
  E -->|GET qa-quickmenu/*| PG
  E -->|POST .../api/search| SS
  SS --> RP
  RP --> PL
  PL --> PG
  E -->|프록시| EMB

  T2 --> E
  T3 --> C
  C --> RD
  LLM --> RD
```

---

## 2. 경로 A: 임베딩 도구 + RAG 검색

| 단계 | 설명 |
|------|------|
| 진입 | `GET /tools/embedding` → 운영자용 임베딩 적재 + 벡터 검색 폼 (`embedding_tool.html`) |
| 검색 API | `POST /tools/embedding/api/search` → `run_vector_search()` (`main/app/rag/search_service.py`) |
| 세션 | 폼으로 `session_id` 를 넘기면, DB에서 최근 대화를 읽어 `ConversationMemory` + `has_history` 로 후행·의도 분류에 반영 |
| 파이프라인 | `execute_retrieval_pipeline()` (`orchestrator.py`): 의도·`retrieval_topic`·언어·쿼리 계획·벡터 검색·RRF·컨텍스트 조립 |
| 벡터 | `pipeline.py` 의 `embed_query_text` / `search_embedding_tables` (원격이면 `EMBEDDING_SERVICE_URL` HTTP) |
| 저장 | 세션 있을 때 사용자 메시지는 **검색·분류 완료 후** `MessageService` → `message` + `message_meta` (intent, `retrieval_topic`, `is_followup` 등) |
| 답변 | `answer_mode`: `template` 또는 OpenAI 기반 |

**관련 파일**

- `main/app/api/routes/embedding_tool.py` — UI + search + **QA 퀵메뉴 JSON API**
- `main/app/rag/search_service.py` — 세션 hydrate, 파이프라인 호출, 저장, 응답 조립
- `main/app/rag/retrieval/orchestrator.py` — 단계별 `step_logs`
- `main/app/rag/retrieval/intent.py` — 라우팅 intent + `retrieval_topic` 이중 축
- `main/app/rag/retrieval/planning.py` — 다중 검색 쿼리 생성
- `main/app/rag/retrieval/search.py` — 실제 벡터 검색 호출
- `main/app/rag/pipeline.py` — pgvector 테이블·임베딩

---

## 2.1 Test_AI: /tools/chatbot 내 저장 FAQ 카테고리

**목적:** 자유 입력(Queue 챗)과 별도로, **DB에 미리 넣어 둔 FAQ(`quickmenu_label` / `question_sample` / `answer_sample`)** 를 카테고리형으로 빠르게 보여 준다.

| 단계 | 설명 |
|------|------|
| 진입 | `GET /tools/chatbot` → `chatbot.html` (상단 카테고리 + 기존 Queue 채팅) |
| 카테고리 로드 | `GET .../qa-quickmenu/primary?qa_user=visitor` 또는 `exhibitor` — `primary_question=true` 행 목록 |
| 선택 시 질문 UI | 버튼 라벨은 `quickmenu_label`; 클릭하면 `question_sample` 이 채팅 질문 UI(입력창 + 사용자 버블)로 자동 표시 |
| 답변 UI | 클릭 항목의 `answer_sample` (없으면 `answer_question` fallback)을 답변 버블로 표시, `links`도 함께 노출 |
| 후속 질문 | `GET .../follow-links` 결과가 있으면 **답변 버블 아래** 후속 질문 버튼 나열 |

**데이터 매핑 (CSV `kprint QA bot_초안.csv`)**

- `qa_user=visitor` + `primary_question=true` → 스크린의 **「참관객 FAQ」** 1차 주제 목록.
- `qa_user=exhibitor` + `primary_question=true` → **「참가업체 FAQ」**.
- 버튼 라벨은 `quickmenu_label`, 질문 본문은 `question_sample`, 답변 본문은 `answer_sample`.

**관련 파일**

- `main/app/templates/chatbot.html` — 상단 FAQ 카테고리 + 기존 Queue/SSE 채팅 통합 UI
- `main/app/db/repositories/kprint_qa_quickmenu_repository.py`
- `scripts/load_kprint_qa_quickmenu.py` — CSV → DB 적재

---

## 3. 경로 B: Redis 큐 + SSE (“큐 챗봇”)

| 단계 | 설명 |
|------|------|
| 질문 등록 | `POST /chat` (`main/app/api/routes/chatbot.py`) — 본문을 Redis 리스트 큐에 JSON으로 push |
| 스트림 | `GET /stream/{request_id}` — 워커가 다른 리스트에 쌓은 토큰/이벤트를 SSE로 소비 |
| 캐시 | 동일 질문 SHA 캐시 키로 Redis GET → 히트 시 즉시 done 이벤트 |
| 워커 | 이 저장소 밖의 프로세스가 `llm_queue_name` 을 소비한다고 가정 (구현은 배포 쪽) |

**API는 LLM을 직접 호출하지 않는다.** 큐 적재 + 추적(`trace`) + SSE만 담당한다.

---

## 4. REST API v1 (`/api/v1`)

`main/app/api/router.py` — `health`, `companies`, `products` 등 **버전 프리픽스 아래** REST.  
RAG 검색은 여기 없고 `/tools/embedding/api/search` 에 있다.

---

## 5. QA 카테고리 퀵메뉴 (`kprint_qa_quickmenu`)

CSV (`docs/kprint QA bot_초안.csv`) → Alembic 테이블 → `scripts/load_kprint_qa_quickmenu.py` 적재.  
Docker: `docker compose exec api python scripts/load_kprint_qa_quickmenu.py` (앱 이미지 **재빌드** 후 신규 모듈 반영).

| HTTP | 용도 |
|------|------|
| `GET /tools/embedding/api/qa-quickmenu/landing` | Test_AI 카테고리 헤더/허브 메타 + primary 개수 |
| `GET /tools/embedding/api/qa-quickmenu/primary` | `primary_question=true` 메인 1차 버튼 후보 (`qa_user`, `domain` 쿼리) |
| `GET /tools/embedding/api/qa-quickmenu/by-parent?parent_id=ko1` | 같은 `parent_id` 그룹 |
| `GET /tools/embedding/api/qa-quickmenu/{qna_code}` | 단일 행 |
| `GET /tools/embedding/api/qa-quickmenu/{qna_code}/follow-links` | `follow_question*` / `default_quickmenu` 에 적힌 코드 순서로 다음 행 |

**코드**

- `main/app/db/repositories/kprint_qa_quickmenu_repository.py`
- `main/app/db/models/kprint_qa_quickmenu.py`

---

## 6. DB 테이블 요약

| 테이블 | 역할 |
|--------|------|
| `conversation_sessions` | 대화 세션 PK(UUID). 문자열 `session_id` 는 서비스에서 UUID로 매핑 |
| `messages` | user/assistant 메시지 본문 |
| `message_meta` | 사용자 메시지별 intent, `retrieval_topic`, follow-up, confidence |
| `kprint_*` (임베딩) | 참가업체·전시품 원본 + pgvector 임베딩 테이블 (RAG 검색 대상) |
| `kprint_qa_quickmenu` | 전시 QA 퀵메뉴/카테고리 (RAG와 별도 트리 UI용) |

---

## 7. 환경 변수 (자주 쓰는 것)

| 변수 | 용도 |
|------|------|
| `DATABASE_URL` | Postgres (동기 `app.db` + 비동기 `app.db.session`) |
| `EMBEDDING_SERVICE_URL` | 쿼리 임베딩 HTTP 프록시 대상 |
| `OPENAI_API_KEY` | 의도 보조·답변 생성 (선택) |
| `REDIS_URL` | 큐 챗봇 캐시/스트림/큐 |

---

## 8. 로컬 개발 순서 (요약)

1. Postgres + Redis 기동, `.env` 에 URL 설정  
2. `alembic upgrade head`  
3. 임베딩·CSV 적재 스크립트는 `scripts/` 참고 (`load_kprint_qa_quickmenu.py` 로 QA 테이블 채움)  
4. `uvicorn app.main:app` 은 보통 `main` 을 PYTHONPATH 에 두고 실행  
5. 브라우저에서 `http://localhost:8000/tools/chatbot` 로 카테고리+Queue 챗 데모 확인  

---

## 9. 용어 정리

| 용어 | 의미 |
|------|------|
| 라우팅 intent | `greeting`, `followup`, `company`, `product`, `general`, `not_related` 등 — 검색 생략 여부·LLM 톤 |
| `retrieval_topic` | `company` / `product` / `all` — 벡터 검색 `entity_scope` |
| `primary_question` (QA 테이블) | 메인 화면에서 먼저 노출할 퀵메뉴 행 여부 (RAG intent 와 별개) |

---

## 10. 의도 파악 순서/방법/처리

`execute_retrieval_pipeline` 기준 실제 순서:

1. **입력 정규화**  
   - 함수: `normalize_user_query()` (`intent.py`)  
   - 처리: 공백 정리, 스마트쿼트/전각물음표 변환, 제어문자 제거  
   - 목적: 분류/플래너 입력 안정화 (형태가 달라도 같은 질문으로 인식)

2. **이중 축 의도 분류** (`classify_intent_v2`)  
   - 축1 라우팅 intent: `greeting`, `not_related`, `general`, `followup`, `company`, `product`  
   - 축2 검색 주제 `retrieval_topic`: `company` / `product` / `all`

3. **분류 내부 판정 방법(우선순위)**  
   - (a) 인사/무관 휴리스틱 즉시 처리  
   - (b) 본문 키워드로 `retrieval_topic` 추정(회사/제품 동시 힌트면 제품 우선)  
   - (c) 후행 질문 여부 판정(짧은질문+히스토리, 대명사, 접속어, memory 엔티티 매칭)  
   - (d) 후행이면 intent는 `followup`으로 고정, topic은 유지  
   - (e) 후행이 아니면 topic 기반으로 `company`/`product` 라우팅  
   - (f) 애매하면 OpenAI fallback(`intent=...;topic=...`, 구형 한 단어 응답도 호환)

4. **분류 결과 처리**  
   - `greeting`/`not_related`/`general`: 검색 생략, 안내 응답  
   - 검색 intent: planner + semantic search + RRF 진행  
   - `entity_scope`는 intent가 아니라 **`retrieval_topic`** 으로 결정

5. **로그/저장 반영**  
   - `step_logs`에 정규화(step 0), 분류(step 1), 언어(step 2) 등 누적  
   - 세션 모드에서는 최종 `intent / is_dialog_followup / retrieval_topic`로 DB 저장

문서 갱신 시점: 저장소 내 코드 기준. 배포 환경별 URL·워커는 다를 수 있다.
