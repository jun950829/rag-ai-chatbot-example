# Local Embedding Mini App

로컬에서 `new_company` 테이블의 데이터를 `Qwen/Qwen3-VL-Embedding-2B`로 임베딩하고 결과 ZIP을 다운로드하는 도구입니다.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn embedding.main:app --host 0.0.0.0 --port 8010 --reload
```

브라우저에서 `http://localhost:8010` 접속 후 실행.

주의:
- 이 앱은 CSV를 읽지 않고 DB의 `new_company`를 조회합니다.
- 따라서 `.env`의 `DATABASE_URL`이 로컬 DB를 가리켜야 합니다.

`embedding/` 디렉토리에서 실행할 경우:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8010 --reload
```

## Output ZIP

- `new_company_profile_embedding_tbd_kor.jsonl`
- `new_company_profile_embedding_tbd_eng.jsonl`
- `new_company_evidence_embedding_tbd_kor.jsonl`
- `new_company_evidence_embedding_tbd_eng.jsonl`
- `summary.json`

