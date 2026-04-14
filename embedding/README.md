# Local Embedding Mini App

로컬에서 `new_company` 테이블을 읽어 `Qwen/Qwen3-Embedding-0.6B`(기본)로 임베딩한 뒤, KOR/ENG 프로필·근거용 **네 개의 pgvector 테이블**에 바로 upsert 합니다.

## Run (프로젝트 루트에서)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn embedding.main:app --host 0.0.0.0 --port 8010 --reload
```

브라우저에서 `http://localhost:8010` 접속 후 실행.

- `.env`의 `DATABASE_URL`(또는 `EMBEDDING_DATABASE_URL`)이 실제 Postgres를 가리켜야 합니다. Docker Compose 밖에서 `db` 호스트가 안 되면 `localhost`로 바꾸거나, 앱이 자동으로 `@db:` → `@localhost:` 치환을 사용합니다.

`embedding/` 디렉토리에서만 실행할 때:

```bash
uvicorn main:app --host 0.0.0.0 --port 8010 --reload
```

## CLI (동일 파이프라인)

```bash
python scripts/embed_new_company_qwen3_profile_evidence.py --limit 100
```
