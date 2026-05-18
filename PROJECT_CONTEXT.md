# exmatch-template 프로젝트 구조 & 프로세스 가이드

> 다른 AI에게 프로젝트를 파악시키기 위한 문서.
> 작성 기준: 2026-05-14

---

## 1. 프로젝트 개요

전시회(KPRINT) 참가기업·전시품 안내 **RAG 챗봇**. 사용자 질문 → 의도 분류 → pgvector 시맨틱 검색(RRF) → LLM(GPT) 답변 스트리밍(SSE) → 카드 캐러셀 반환.

| 계층 | 기술 스택 |
|---|---|
| Backend | Python 3.11 · FastAPI · SQLAlchemy · pgvector · Redis · OpenAI API |
| Frontend (신규) | Next.js 16 · TypeScript · React · Zustand · TanStack Query · Tailwind CSS |
| Frontend (구버전) | Vite · React · TypeScript |
| Infra | Docker Compose · EC2 (메인 API + 프론트) · EC2 (임베딩 워커) |

---

## 2. 디렉토리 구조 (핵심만)

```
exmatch-template/
├── new_main/                          ← 현재 활성 백엔드 + 프론트
│   ├── app/
│   │   ├── api/
│   │   │   ├── chat.py                ← POST /chat, POST /chat/card-detail 엔드포인트
│   │   │   ├── tools_compat.py        ← 기존 호환 라우터
│   │   │   └── quickmenu_sync.py
│   │   ├── core/
│   │   │   ├── config.py              ← Settings (pydantic-settings, .env 로드)
│   │   │   └── logger.py
│   │   ├── services/
│   │   │   ├── chat_pipeline.py       ★ 메인 파이프라인 오케스트레이터 (9단계)
│   │   │   ├── suggestion_cards.py    ← 검색 행 → 카드 변환 로직
│   │   │   └── steps/                 ← 파이프라인 각 단계 모듈
│   │   │       ├── normalize.py       ← 1단계: 질문 정규화
│   │   │       ├── language.py        ← 2단계: 언어 감지 (ko/en)
│   │   │       ├── cache.py           ← 3단계: Redis 캐시 조회/저장
│   │   │       ├── intent.py          ← 4단계: 의도 분류 + early exit 처리
│   │   │       ├── search_queries.py  ← 5단계: 다중 쿼리 계획 (LLM 확장)
│   │   │       ├── retrieval.py       ← 6단계: pgvector 검색 + RRF 호출
│   │   │       ├── make_cards.py      ← 7단계: 카드 생성 + 카탈로그 hydrate
│   │   │       ├── prompt.py          ← 8단계: 프롬프트 조립
│   │   │       └── llm_stream.py      ← 8-9단계: OpenAI 스트리밍 호출
│   │   ├── prompt/
│   │   │   ├── retrieval_answer.py    ← RAG 답변 시스템/유저 메시지 빌더
│   │   │   ├── card_detail.py         ← 카드 상세 클릭 시 메시지 빌더
│   │   │   ├── citation.py            ← 출처 정책 상수
│   │   │   └── general_chat.py
│   │   ├── retrieval/
│   │   │   ├── retrieval.py           ← 검색 파이프라인 (multi-query → RRF → cutoff)
│   │   │   ├── retrieval_steps.py     ← semantic_search, rrf_fuse, cutoff 등
│   │   │   ├── vector_db.py           ← pgvector 쿼리, 카탈로그 조회, homepage 조회
│   │   │   └── embedding_client.py    ← 임베딩 서비스 호출
│   │   ├── streaming/
│   │   │   └── sse.py                 ← SSE 이벤트 포맷터 (delta → cards → done)
│   │   ├── rag/faq/                   ← FAQ 검색 (별도 파이프라인)
│   │   ├── observability/tracing.py   ← trace_stage 컨텍스트 매니저
│   │   └── main.py                    ← FastAPI app 생성 (CORS, 라우터, 정적파일)
│   │
│   ├── frontend/                      ★ 신규 Next.js 프론트엔드
│   │   └── src/
│   │       ├── views/home/
│   │       │   ├── home.view.tsx      ← 메인 뷰 (메시지 목록, 스트리밍, 모드 전환)
│   │       │   └── components/        ← ChatInput, MessageList, ModeSelector, IntroOverlay
│   │       ├── hooks/chat/
│   │       │   ├── use-chat-stream.ts ← SSE 소비, sendMessage, sendCardDetail
│   │       │   ├── use-bootstrap-thread.ts  ← 스레드 초기화
│   │       │   └── use-update-thread-mode.ts ← 모드 전환
│   │       ├── services/
│   │       │   └── chat.service.ts    ← API 호출 (streamMessage, streamCardDetail, 환영 메시지)
│   │       ├── stores/
│   │       │   └── chat.store.ts      ← Zustand 상태 (messages, threadId, sessionMode, streaming)
│   │       ├── components/shared/
│   │       │   ├── catalog-card-list.tsx ← 카드 캐러셀 + "자세히 보기" 버튼
│   │       │   ├── chat-response.tsx    ← 답변 버블 (RichContent)
│   │       │   └── rich-content.tsx     ← 마크다운 렌더링 + 불릿 정규화
│   │       └── lib/utils.ts           ← generateId() (crypto.randomUUID 폴백)
│   │
│   ├── frontend_old_version/          ← 구 Vite+React 프론트 (deploy_ec2_all.sh로 배포)
│   ├── docker-compose.ec2-1.yml       ← EC2 Docker Compose (api, redis, postgres)
│   ├── Dockerfile                     ← 백엔드 Docker 이미지
│   └── .env                           ← 환경변수 (API 키 등)
│
├── embedding/                         ← 임베딩 워커 (별도 EC2)
├── main/                              ← 이전 버전 백엔드 (참고용)
├── scripts/
│   ├── deploy_ec2_all.sh              ← 메인 배포 (old_version 프론트 + 백엔드)
│   └── deploy_ec2_new_front.sh        ← 신규 Next.js 프론트 배포 (포트 3001)
└── data/                              ← 데이터 시드 파일
```

---

## 3. 백엔드 메인 파이프라인 (`chat_pipeline.py`)

`chat_stream(session_id, message)` → `(cards[], AsyncIterator[str])`

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1) normalize_question(message)            → normalized              │
│ 2) detect_language(normalized)            → language (ko|en)        │
│ 3) get_cached_answer(normalized)          → 캐시 히트 시 즉시 반환  │
│ 4) classify_intent(normalized)            → intent                  │
│    └ resolve_early_exit(intent, ...)      → empty/greeting 즉시 반환│
│ 5) plan_retrieval_search_queries(...)     → search_queries[]        │
│ 6) retrieve_answer_context(...)           → context, rows           │
│ 7) make_cards(rows, context, ...)         → cards[], enriched_ctx   │
│ 8) build_chat_messages(...)               → messages (system+user)  │
│ 9) stream_llm_answer(messages) + cache    → token stream (SSE)      │
└─────────────────────────────────────────────────────────────────────┘
```

### 각 단계 상세

**1) 정규화** (`steps/normalize.py`)
- 사용자 입력 전처리 (공백, 특수문자 정리)

**2) 언어 감지** (`steps/language.py`)
- 한글 vs 영어 문자 비율 기반 (영어 비율 > 0.7이면 `en`, 아니면 `ko`)
- 이후 모든 단계(검색 쿼리, 프롬프트, LLM 응답)의 언어를 결정

**3) 캐시** (`steps/cache.py`)
- Redis에 `chat:answer:{SHA256(normalized)}` 키로 저장 (TTL 1시간)
- 히트 시 검색/LLM 없이 캐시된 텍스트 즉시 반환 (카드 없음)

**4) 의도 분류** (`steps/intent.py`)
- `_heuristic_intent`: 패턴 매칭 (greeting, company_query, product_query, empty)
  - 20자 이하 + greeting 패턴 → `"greeting"`
  - 기업 힌트 키워드 → `"company_query"`
  - 제품 힌트 키워드 → `"product_query"`
- `_llm_classify_intent`: 휴리스틱 미확정 시 OpenAI로 보정
- `resolve_early_exit`: `empty` → 안내 메시지, `greeting` → 고정 인사 응답 (LLM 미호출)

**5) 다중 쿼리** (`steps/search_queries.py`)
- 짧은 입력(< 45자) 또는 휴리스틱 축 미확정 → LLM으로 3~5개 검색 쿼리 확장
- LLM 실패 시 규칙 기반 fallback 쿼리 생성
- 충분히 긴/명확한 입력 → 단일 쿼리만 사용

**6) 검색** (`steps/retrieval.py` → `retrieval/retrieval.py`)
- 각 쿼리를 pgvector 임베딩 검색 (코사인 유사도)
- Reciprocal Rank Fusion (RRF)으로 결과 병합
- `card_rows`: merge 전 개별 행 (카드용, 최대 10개)
- `context`: merge 후 텍스트 (LLM 프롬프트용, cutoff 적용)

**7) 카드 + hydrate** (`steps/make_cards.py`)
- `build_cards_from_rows`: 검색 행에서 title/subtitle/entity_kind/external_id 추출
- `_hydrate_cards_with_catalog`: 카탈로그 테이블에서 image_url, 제조사, 전시장, 웹사이트 보강
  - 제품 카드: 제조사 회사명 → 업체 테이블에서 homepage 조회
- enriched_ctx: 카탈로그 구조화 필드를 LLM 컨텍스트에 추가

**8-9) 프롬프트 + LLM 스트리밍**
- `build_chat_messages`: intent에 따라 제품/업체 형식 선택, 언어별 system prompt 조립
- `stream_llm_answer`: OpenAI Chat Completions 스트리밍
- 스트리밍 완료 후 Redis에 전체 응답 캐시 저장

---

## 4. API 엔드포인트

### `POST /chat`
- Form: `session_id`, `message`
- Response: SSE stream
  - `event: delta` → 토큰 조각 (문자열)
  - `event: cards` → 카드 배열 JSON (텍스트 스트리밍 완료 후)
  - `event: done` → `"[DONE]"`

### `POST /chat/card-detail`
- Form: `session_id`, `external_id`, `entity_kind?`, `language?`
- 카드 클릭 시 해당 항목의 DB 데이터로 LLM 답변 스트리밍 (새 검색 없음)
- Response: SSE stream (delta → done, 카드 없음)

---

## 5. SSE 스트리밍 포맷 (`streaming/sse.py`)

```
event: delta
data: "안녕"

event: delta
data: "하세요"

event: cards
data: [{"title":"...", "subtitle":"...", "entity_kind":"exhibit_item", "external_id":"...", "image_url":"...", "website":"..."}]

event: done
data: "[DONE]"
```

- 텍스트 토큰(delta)을 먼저 모두 보낸 뒤, 카드가 있으면 한 번에 전송, 마지막에 done
- 에러 발생 시 `event: error` 전송 후 done

---

## 6. 프론트엔드 (Next.js) 동작 흐름

### 상태 관리 (`chat.store.ts` — Zustand)
- `threadId`: 현재 세션 ID (프론트에서 생성, 백엔드 session_id로 사용)
- `sessionMode`: `catalog` | `faq_visitor` | `faq_exhibitor`
- `messages[]`: 전체 대화 내역 (질문 + 답변 + 카드)
- `isStreaming`, `currentStreamingMessage`: 스트리밍 상태
- persist: `threadId`와 `sessionMode`만 localStorage에 유지

### 메인 뷰 흐름 (`home.view.tsx`)
1. 초기 화면: `IntroOverlay` — 카테고리 선택 (catalog/faq_visitor/faq_exhibitor)
2. 카테고리 클릭 → `bootstrapThread` (threadId 생성 + 환영 메시지 append)
3. 이미 threadId 있으면 `updateThreadMode` (기존 대화 유지 + 환영 메시지 append)
4. 질문 입력 → `sendMessage` → SSE 스트리밍 소비
5. 카드 "자세히 보기" 클릭 → `sendCardDetail` → card-detail SSE 소비

### SSE 소비 (`use-chat-stream.ts`)
- `consumeSSEStream`: ReadableStream을 읽으며 event별 처리
  - `delta` → `updateStreamingMessage` (실시간 텍스트 누적)
  - `cards` → `pendingCards`에 저장
  - `done` → `finishStreaming` (최종 답변 + 카드를 messages에 추가)

### API 호출 (`chat.service.ts`)
- `streamMessage(sessionId, {message})` → `POST /chat` (FormData)
- `streamCardDetail(sessionId, externalId, entityKind)` → `POST /chat/card-detail` (FormData)
- `createThread`, `updateThreadMode` → 서버 없이 로컬에서 synthetic 처리 (환영 메시지 포함)

---

## 7. 데이터베이스 테이블 (주요)

| 테이블 | 용도 |
|---|---|
| `kprint_exhibitor` | 참가업체 정보 (회사명, homepage, 부스, 국가 등) |
| `kprint_exhibit_item` | 전시품/제품 정보 (제품명, 제조사, 이미지, 카테고리 등) |
| `kprint_embeddings` | pgvector 임베딩 청크 (content, embedding, external_id, table_name) |

---

## 8. 배포

### `deploy_ec2_all.sh` (메인 배포)
1. 로컬에서 `frontend_old_version` npm build → dist 생성
2. rsync로 `new_main/` → EC2 메인 서버
3. Docker 컨테이너(api)에 app + dist 복사 후 재시작
4. rsync로 `embedding/` → EC2 임베딩 서버, 워커 재시작

### `deploy_ec2_new_front.sh` (신규 프론트 배포)
1. 로컬에서 Next.js standalone 빌드 (`NEXT_PUBLIC_API_ENDPOINT=http://<EC2_IP>:8000`)
2. rsync로 standalone → EC2 `frontend_next/`
3. EC2에서 포트 3001의 기존 프로세스 kill → `node server.js` 기동

### 접속 URL
- 구버전 프론트: `http://<EC2_IP>:8000`
- 신규 프론트: `http://<EC2_IP>:3001`
- API 직접: `http://<EC2_IP>:8000/chat`

---

## 9. 주요 설정값 (`config.py` → `.env`)

| 키 | 기본값 | 설명 |
|---|---|---|
| `OPENAI_API_KEY` | (필수) | OpenAI API 키 |
| `OPENAI_MODEL` | `gpt-4o-mini` | LLM 모델 |
| `REDIS_URL` | | Redis 연결 (캐시용) |
| `POSTGRES_DSN` | | PostgreSQL + pgvector |
| `EMBEDDING_SERVICE_URL` | | 임베딩 워커 URL |
| `RETRIEVAL_TOP_K` | 8 | 검색 상위 K개 |
| `RETRIEVAL_MULTIQUERY_MIN/MAX` | 3/5 | 다중 쿼리 개수 범위 |
| `RETRIEVAL_MULTIQUERY_SHORT_CHARS` | 45 | 이 길이 미만이면 다중 쿼리 확장 |
| `INTENT_USE_OPENAI` | true | LLM 의도 분류 사용 여부 |

---

## 10. 핵심 규칙 및 설계 원칙

1. **`chat_pipeline.py`는 순수 오케스트레이터**: 단계별 호출만 나열, 세부 로직은 `steps/` 모듈로 분리
2. **카드는 텍스트 스트리밍 완료 후 전송**: delta → cards → done 순서
3. **캐시 히트 시 카드 없음**: Redis 캐시는 텍스트만 저장
4. **greeting은 LLM 미호출**: 고정 메시지로 즉시 응답
5. **언어 감지 → 전체 파이프라인에 전파**: 검색 쿼리, 프롬프트, LLM 응답 모두 감지된 언어 사용
6. **카탈로그 hydrate**: 검색 결과(임베딩 청크)에 구조화 DB 필드를 보강하여 카드와 LLM 컨텍스트 풍부화
7. **프론트엔드 스레드 = 로컬**: 백엔드에 스레드/히스토리 개념 없음, session_id만 전달
8. **이미지 referrerPolicy**: S3 pre-signed URL → `referrerPolicy="no-referrer"` 필수
9. **웹사이트 = 업체 homepage**: 제품 카드의 website는 제조사 회사의 homepage, 이미지 링크가 아님
