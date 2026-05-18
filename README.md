# Exmatch RAG App Template

전시회·카탈로그 안내용 **RAG 챗봇** 템플릿입니다. 팀이 새 프로젝트를 시작할 때 재사용할 수 있는 구조, 문서, Docker/Alembic 설정을 담고 있습니다.

현재 **활성 스택**은 다음과 같습니다.

| 영역 | 경로 | 설명 |
|------|------|------|
| 백엔드 | `new_main/` | FastAPI · 채팅 파이프라인 · FAQ · pgvector 검색 |
| 프론트엔드 | `new_main/frontend/` | Next.js 16 · TypeScript · SSE 스트리밍 UI |
| DB 마이그레이션 | `alembic/` (레포 루트) | Postgres + pgvector 스키마 버전 관리 |
| 임베딩 워커 | `embedding/` | 별도 EC2/호스트에서 돌리는 임베딩 HTTP API |

`main/` 과 루트 `docker-compose.yml` 은 **이전 참조 구현**입니다. 신규 작업은 `new_main` 기준으로 진행합니다.

상세 플로우·배포는 [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) 를 참고하세요.

---

## 왜 이 템플릿이 있는가

- 전시/도메인 데이터(업체·제품·FAQ)를 ingest → 임베딩 → 검색 → 제한된 답변 생성까지 **같은 형태**로 반복 구축
- RAG 파이프라인·프롬프트·인프라 지식을 **코드와 문서**로 공유
- FastAPI + Postgres(pgvector) + Redis + (선택) 임베딩 서버 조합을 팀 표준으로 유지

---

## 전체 흐름

```text
사용자 (Next.js UI)
    → POST /chat (SSE)
        → 정규화 · 언어 · Redis 캐시 · 의도
        → 다중 쿼리 계획 → pgvector 검색(RRF) → 카드 생성
        → OpenAI 스트리밍 답변
    ← delta / cards / done (또는 FAQ 모드 시 final)

임베딩 API (embedding/, 별도 호스트)
    ← EMBEDDING_SERVICE_URL 로 질의 벡터화
```

FAQ 모드(`faq_visitor`, `faq_exhibitor`)는 카탈로그 파이프라인과 분리된 `new_main/app/rag/faq/` 경로를 탑니다.

---

## 저장소 구조

```text
rag-ai-chatbot-example/
├── new_main/                    # ★ 활성 백엔드 + 프론트
│   ├── app/
│   │   ├── api/                 # chat, tools_compat, quickmenu_sync
│   │   ├── core/                # config, logger
│   │   ├── services/            # chat_pipeline + steps/
│   │   ├── retrieval/           # pgvector, RRF, embedding_client
│   │   ├── rag/faq/             # FAQ 파이프라인
│   │   ├── prompt/              # LLM 메시지 빌더
│   │   ├── streaming/           # SSE 포맷
│   │   └── main.py
│   ├── frontend/                # ★ Next.js 챗 UI
│   ├── docker-compose.ec2-1.yml
│   ├── Dockerfile
│   ├── .env.example
│   └── requirements.txt
│
├── alembic/                     # ★ DB 마이그레이션 (레포 루트)
│   ├── env.py                   # ORM: main/app/models
│   └── versions/
│
├── embedding/                   # 임베딩 HTTP API (GPU/CPU, 별도 배포)
├── main/                        # 레거시 백엔드 (참고)
├── docker-compose.yml           # 레거시 로컬 스택 (main 기준)
├── scripts/                     # ingest, deploy 스크립트
└── data/                        # 시드 CSV 등
```

### `new_main/app` 파이프라인 (카탈로그 모드)

`services/chat_pipeline.py` 가 9단계를 오케스트레이션합니다.

1. 질문 정규화 · 2. 언어 감지 · 3. Redis 캐시 · 4. 의도 분류  
5. 검색 쿼리 확장 · 6. pgvector + RRF · 7. 카드 생성/hydrate  
8. 프롬프트 조립 · 9. OpenAI 스트리밍 + 캐시 저장  

각 단계는 `services/steps/` 모듈에 분리되어 있습니다.

---

## 사전 요구사항

- Docker & Docker Compose (권장)
- Python 3.11+ (로컬 API 실행 시)
- Node.js 20+ (프론트 개발 시)
- OpenAI API 키 (`OPENAI_API_KEY`)
- 검색용 **임베딩 서버** URL (`EMBEDDING_SERVICE_URL`) — 로컬 또는 EC2

---

## 빠른 시작 (Docker, 권장)

`new_main` 디렉터리에서 전체 스택(API · Redis · Postgres · Next.js)을 띄웁니다.

```bash
cd new_main
cp .env.example .env
# .env 에 OPENAI_API_KEY, EMBEDDING_SERVICE_URL 등 설정

docker compose -f docker-compose.ec2-1.yml up --build
```

| 서비스 | URL |
|--------|-----|
| API | http://localhost:8000 |
| API 문서 (FastAPI) | http://localhost:8000/docs |
| Next.js UI | http://localhost:3001 |
| Postgres | `localhost:5432` (DB: `chatbot`, user/pass: `postgres`) |
| Redis | `localhost:6379` |

Compose의 API·Redis·Postgres는 **같은 Docker 네트워크(`backend`)** 에 있어야 합니다.  
`REDIS_URL=redis://redis:6379/0`, `POSTGRES_DSN=postgresql+asyncpg://postgres:postgres@postgres:5432/chatbot` 형태를 `.env.example` 에 맞춥니다.

프론트 빌드 시 API 주소는 compose build arg 로 넘깁니다.

```yaml
# docker-compose.ec2-1.yml
NEXT_PUBLIC_API_ENDPOINT: "http://localhost:8000"
```

---

## 데이터베이스 (Alembic)

스키마 변경은 **레포 루트**의 Alembic으로 관리합니다.  
`alembic/env.py` 는 `main/app` 의 SQLAlchemy 모델·`DATABASE_URL` 설정을 사용합니다 (`prepend_sys_path = .:main`).

### 마이그레이션 적용

Postgres가 떠 있는 상태에서, **프로젝트 루트**에서:

```bash
# new_main compose Postgres에 맞춘 예시
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/chatbot

# 또는 main/.env 와 동일한 DSN
pip install -r new_main/requirements.txt
pip install -r requirements-api.txt   # 루트 공통 의존성(alembic 등)

alembic upgrade head
```

새 리비전 생성:

```bash
alembic revision -m "describe_change" --autogenerate
# 생성된 alembic/versions/*.py 검토 후
alembic upgrade head
```

루트 `docker-compose.yml` (레거시 `main` 스택) API 컨테이너는 기동 시 `RUN_MIGRATIONS=1` 이면 `alembic upgrade head` 를 자동 실행합니다 (`docker/entrypoint.sh`).  
`new_main` compose는 **수동으로** 위 명령을 실행하는 것을 기본으로 합니다.

주요 마이그레이션 예: `kprint_exhibitor`, `kprint_exhibit_item`, `kprint_embeddings`(pgvector HNSW), 채팅 persist, QA quickmenu 등 — `alembic/versions/` 참고.

---

## 로컬 개발 (Docker 없이)

### API

```bash
cd new_main
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# POSTGRES_DSN, REDIS_URL 을 localhost 기준으로 수정
#   예: redis://127.0.0.1:6379/0
#       postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/chatbot

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 프론트엔드 (Next.js)

```bash
cd new_main/frontend
npm ci
export NEXT_PUBLIC_API_ENDPOINT=http://localhost:8000
npm run dev
```

기본 개발 서버: http://localhost:3000 (`package.json` 의 `next dev`).

프론트는 `POST /chat`, `POST /chat/card-detail` 에 **FormData + SSE(POST)** 로 붙습니다.  
`EventSource`(GET 전용)가 아니라 `fetch` + ReadableStream 파서를 사용합니다 (`hooks/chat/use-chat-stream.ts`).

### 임베딩 워커 (별도 프로세스)

벡터 검색·배치 임베딩용 HTTP API는 `embedding/` 에 있습니다. API 컨테이너/프로세스와 **분리**해 두는 것이 일반적입니다.

```bash
# 프로젝트 루트
export PYTHONPATH="$(pwd)/main"
pip install -r requirements-api.txt -r embedding/requirements.txt
bash embedding/install_deps.sh cpu
uvicorn embedding.main:app --reload --host 0.0.0.0 --port 8765
```

`new_main/.env` 의 `EMBEDDING_SERVICE_URL=http://127.0.0.1:8765` 로 연결합니다.  
자세한 내용: [`embedding/README.md`](embedding/README.md).

---

## API 요약 (`new_main`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/chat` | 카탈로그/FAQ 채팅 (Form: `session_id`, `message`, `session_mode`) → SSE |
| `POST` | `/chat/card-detail` | 카드 상세 스트리밍 |
| — | `/tools/...` | 임베딩·검색 도구 호환 (`tools_compat`) |

**카탈로그 SSE 이벤트:** `delta` → (선택) `cards` → `done`  
**FAQ SSE 이벤트:** `final` (답변 + 카드 메타)

`session_mode`: `catalog` | `faq_visitor` | `faq_exhibitor`

프론트의 `threadId`는 로컬(Zustand)에서 생성하며, 백엔드에는 `session_id` 로만 전달됩니다(서버 측 스레드 DB 없음).

---

## 환경 변수 (`new_main/.env.example`)

| 변수 | 설명 |
|------|------|
| `OPENAI_API_KEY` | RAG 답변·의도·다중 쿼리 (필수) |
| `POSTGRES_DSN` | async SQLAlchemy DSN |
| `REDIS_URL` | 답변 캐시 |
| `EMBEDDING_SERVICE_URL` | 임베딩 HTTP API |
| `INTENT_USE_OPENAI` | LLM 의도 분류 사용 여부 |
| `RETRIEVAL_*` | multi-query, top_k 등 (주석 참고) |

로깅: `LOG_LEVEL`, `LOG_DIR` (`app/core/logger.py`).

---

## 배포 참고

- **메인 스택:** `new_main/docker-compose.ec2-1.yml` (EC2-1: API + Redis + Postgres + frontend)
- **임베딩:** `embedding/docker-compose.ec2-2.yml` (EC2-2)
- 스크립트: `scripts/deploy_ec2_all.sh`, `scripts/deploy_ec2_new_front.sh`
- 구 Vite UI: `new_main/frontend_old_version/` (정적 빌드를 API에 마운트하는 경로도 존재)

---

## 개발 원칙

- 파이프라인은 `chat_pipeline.py` + `steps/` 로 **단계별 추적** 가능하게 유지
- 도메인 규칙(프롬프트·의도·카드)과 공통 RAG 블록(검색·RRF) 분리
- 외부 의존성(OpenAI, Postgres, Redis, 임베딩 URL)은 **환경 변수**로 교체
- DB 스키마는 **Alembic 리비전**으로만 변경 (수동 DDL 최소화)
- 배치 임베딩·인덱스 갱신을 기본으로, 실시간 갱신은 필요 시 추가

---

## 커밋·브랜치 (팀 규칙)

컨벤셔널 커밋: `feat:`, `fix:`, `chore:`, `refactor:`

단계별 브랜치 예: `feat/foundation`, `feat/ingestion`, `feat/embeddings`, `feat/retrieval`, `feat/chat-runtime`

---

## 레거시 / 참고

| 경로 | 용도 |
|------|------|
| `main/` | 이전 FastAPI·RAG·임베딩 UI (`/tools/embedding`) |
| `main/frontend/` | Vite + React (구 UI) |
| `docker-compose.yml` | `main` + worker + db 템플릿용 compose |
| `docs/CHATBOT_ARCHITECTURE.md` | 아키텍처 상세 (일부 `main` 기준 문구 포함) |

신규 기능·문서는 **`new_main` + `alembic` + `new_main/frontend`** 를 기준으로 맞춥니다.

---

## 상태

- **백엔드·RAG·FAQ:** `new_main` 에서 운영 중
- **UI:** `new_main/frontend` (Next.js) — 로컬/EC2 3001
- **DB:** Alembic 리비전 + pgvector
- **임베딩:** `embedding/` 별도 서비스

템플릿으로서의 다음 단계: ingest/refresh 자동화, 평가(evaluation), CI, `new_main` 전용 ORM으로 Alembic `env.py` 정리 등.
