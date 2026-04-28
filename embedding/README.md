# Local embedding worker (GPU / sentence-transformers)

이 디렉터리는 **로컬 머신에서만** 돌리는 **임베딩 추론 전용 HTTP API**입니다.  
벡터 검색·의도 분류·UI는 **`main/app/` (Docker에서 실행되는 API)** 의 `app/rag/` 와 `/tools/embedding` 에 있습니다.

## 구조 요약

| 위치 | 역할 |
|------|------|
| `embedding/embed_server.py` | 로컬 임베딩 API (`/v1/embed/query`, `/embed`, `/embed/job`, …) |
| `embedding/main.py` | `uvicorn embedding.main:app` 호환용 엔트리포인트 |
| `main/app/rag/pipeline.py` | DB 읽기/쓰기, 배치 임베딩, pgvector 검색 SQL (API 프로세스에서 사용) |
| `main/app/rag/retrieval.py` | 의도·쿼리 계획·RRF 등 검색 파이프라인 |
| `main/app/rag/search_service.py` | 검색 + OpenAI 답변 조립 |
| `main/app/templates/embedding_tool.html` | 임베딩/검색 UI (브라우저는 API 서버에만 붙음) |

로컬 워커는 `app.rag.pipeline` 을 import 하므로, **`main` 폴더를 `PYTHONPATH`에 두고** 실행해야 합니다.

## 로컬 임베딩 서버 실행 (호스트)

프로젝트 루트에서:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-api.txt
pip install -r embedding/requirements.txt
export PYTHONPATH="$(pwd)/main"
uvicorn embedding.main:app --host 0.0.0.0 --port 8765
```

- Postgres: `.env` 의 `DATABASE_URL` 또는 `EMBEDDING_DATABASE_URL` (임베딩 upsert가 DB에 쓸 때).
- API 문서: `http://localhost:8765/docs`

## Docker API + 로컬 임베딩 연동

1. 위와 같이 호스트에서 포트 **8765** 로 임베딩 서버 실행.
2. Docker Compose API 컨테이너에 `EMBEDDING_SERVICE_URL=http://host.docker.internal:8765` (compose에 기본값 있음).
3. 브라우저: `http://localhost:8000/tools/embedding`  
   - 임베딩 적재 요청은 API → 로컬 임베딩 서버로 프록시  
   - 검색은 API 프로세스의 `main/app/rag` 가 DB 조회 후, 질문 벡터만 로컬 `POST /v1/embed/query` 로 요청

## CLI 배치 임베딩 (동일 파이프라인)

```bash
export PYTHONPATH="$(pwd)/main"
python scripts/embed_koba_qwen3_profile_evidence.py --entity exhibitor --limit 100
```
