"""FAQ 번역 + 임베딩 생성 스크립트.

실행:
    cd embedding
    python -m worker.faq_embed

동작:
    1) kprint_qa_quickmenu 에서 question_sample/answer_sample 조회
    2) OpenAI 로 한→영 배치 번역 후 question_sample_eng / answer_sample_eng 저장
    3) 임베딩 서버(/v1/embed/queries)로 한국어 질문 임베딩 → kprint_qa_quickmenu_embedding_qwen3_0_6b_kor 저장
    4) 임베딩 서버로 영어 질문 임베딩 → kprint_qa_quickmenu_embedding_qwen3_0_6b_eng 저장
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import psycopg
from openai import OpenAI

from worker.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("faq_embed")

_MODEL_ID = settings.retrieval_model_id  # "Qwen/Qwen3-Embedding-0.6B"
_DEVICE = settings.retrieval_device       # "cpu"
_EMB_KOR = "kprint_qa_quickmenu_embedding_qwen3_0_6b_kor"
_EMB_ENG = "kprint_qa_quickmenu_embedding_qwen3_0_6b_eng"
_TRANSLATE_BATCH = 20   # OpenAI 한 번에 번역할 FAQ 수
_EMBED_BATCH = 16       # 임베딩 서버 한 번에 처리할 텍스트 수


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------

@dataclass
class FaqRow:
    qna_code: str
    question_sample: str
    answer_sample: str
    question_sample_eng: str | None
    answer_sample_eng: str | None


# ---------------------------------------------------------------------------
# DB 헬퍼
# ---------------------------------------------------------------------------

def _sync_dsn(dsn: str) -> str:
    """asyncpg DSN → psycopg DSN 변환."""
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


def fetch_faq_rows(conn: psycopg.Connection) -> list[FaqRow]:
    rows = conn.execute(
        """
        SELECT qna_code,
               coalesce(question_sample, '') AS question_sample,
               coalesce(answer_sample, '')   AS answer_sample,
               question_sample_eng,
               answer_sample_eng
          FROM kprint_qa_quickmenu
         WHERE coalesce(trim(question_sample), '') <> ''
         ORDER BY qna_code
        """
    ).fetchall()
    return [
        FaqRow(
            qna_code=r[0],
            question_sample=r[1],
            answer_sample=r[2],
            question_sample_eng=r[3],
            answer_sample_eng=r[4],
        )
        for r in rows
    ]


def save_translations(conn: psycopg.Connection, updates: list[tuple[str, str, str]]) -> None:
    """(question_eng, answer_eng, qna_code) 튜플 리스트를 DB에 저장."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            UPDATE kprint_qa_quickmenu
               SET question_sample_eng = %s,
                   answer_sample_eng   = %s,
                   updated_at          = now()
             WHERE qna_code = %s
            """,
            updates,
        )
    conn.commit()


def upsert_embeddings(
    conn: psycopg.Connection,
    table: str,
    rows: list[dict[str, Any]],
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            f"""
            INSERT INTO {table}
                   (id, faq_id, lang, content, content_hash, embedding_dim, embedding, model, created_at, updated_at)
            VALUES (%(id)s, %(faq_id)s, %(lang)s, %(content)s, %(content_hash)s,
                    %(embedding_dim)s, %(embedding)s::vector, %(model)s, now(), now())
            ON CONFLICT (faq_id, content_hash) DO UPDATE
               SET embedding     = EXCLUDED.embedding,
                   embedding_dim = EXCLUDED.embedding_dim,
                   updated_at    = now()
            """,
            rows,
        )
    conn.commit()


# ---------------------------------------------------------------------------
# 번역
# ---------------------------------------------------------------------------

def _translate_batch(client: OpenAI, items: list[FaqRow]) -> list[tuple[str, str]]:
    """OpenAI 로 한국어 Q&A 배치를 영어로 번역. (question_eng, answer_eng) 리스트 반환."""
    numbered = "\n".join(
        f"{i + 1}. Q: {r.question_sample}\n   A: {r.answer_sample}"
        for i, r in enumerate(items)
    )
    system_prompt = (
        "You are a professional translator for an exhibition event chatbot.\n"
        "Translate the following Korean FAQ Q&A pairs into natural English.\n"
        "Return a JSON array in the same order, each element: "
        '{"q": "<translated question>", "a": "<translated answer>"}\n'
        "Do not add explanations. Output only the JSON array."
    )
    resp = client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": numbered},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = (resp.choices[0].message.content or "").strip()
    parsed = json.loads(raw)

    # 단일 객체 {"q": ..., "a": ...} → 배열로 감싸기
    if isinstance(parsed, dict) and "q" in parsed and "a" in parsed:
        parsed = [parsed]
    elif isinstance(parsed, dict):
        for val in parsed.values():
            if isinstance(val, list):
                parsed = val
                break
    if not isinstance(parsed, list):
        raise ValueError(f"번역 응답 형식 오류: {raw[:200]}")

    out: list[tuple[str, str]] = []
    for entry in parsed:
        q = str(entry.get("q") or "").strip()
        a = str(entry.get("a") or "").strip()
        out.append((q, a))
    return out


def run_translation(client: OpenAI, rows: list[FaqRow]) -> list[FaqRow]:
    """번역이 필요한 행만 번역하고 업데이트된 FaqRow 리스트 반환."""
    need = [r for r in rows if not (r.question_sample_eng and r.answer_sample_eng)]
    log.info("번역 필요: %d / 전체: %d", len(need), len(rows))

    for i in range(0, len(need), _TRANSLATE_BATCH):
        batch = need[i : i + _TRANSLATE_BATCH]
        log.info("  번역 배치 %d~%d ...", i + 1, i + len(batch))
        translated = _translate_batch(client, batch)
        for row, (q_eng, a_eng) in zip(batch, translated):
            row.question_sample_eng = q_eng
            row.answer_sample_eng = a_eng

    return rows


# ---------------------------------------------------------------------------
# 임베딩
# ---------------------------------------------------------------------------

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _call_embed_api(texts: list[str], base_url: str) -> list[list[float]]:
    endpoint = base_url.rstrip("/") + "/v1/embed/queries"
    resp = httpx.post(
        endpoint,
        data={
            "queries": json.dumps(texts, ensure_ascii=False),
            "model_id": _MODEL_ID,
            "device": _DEVICE,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    payload = resp.json()
    embeddings = payload.get("embeddings")
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise RuntimeError(f"임베딩 응답 오류: {payload}")
    return [[float(x) for x in vec] for vec in embeddings]


def run_embedding(
    conn: psycopg.Connection,
    rows: list[FaqRow],
    embed_base_url: str,
) -> None:
    kor_texts = [r.question_sample for r in rows]
    eng_texts = [r.question_sample_eng or "" for r in rows]

    log.info("한국어 임베딩 생성 중 (%d개)...", len(rows))
    kor_vecs = _embed_in_batches(kor_texts, embed_base_url)

    log.info("영어 임베딩 생성 중 (%d개)...", len(rows))
    eng_vecs = _embed_in_batches(eng_texts, embed_base_url)

    kor_records = _build_records(rows, kor_vecs, lang="kor", use_eng=False)
    eng_records = _build_records(rows, eng_vecs, lang="eng", use_eng=True)

    log.info("한국어 임베딩 DB 저장 중...")
    upsert_embeddings(conn, _EMB_KOR, kor_records)

    log.info("영어 임베딩 DB 저장 중...")
    upsert_embeddings(conn, _EMB_ENG, eng_records)

    log.info("임베딩 저장 완료.")


def _embed_in_batches(texts: list[str], base_url: str) -> list[list[float]]:
    results: list[list[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        batch = texts[i : i + _EMBED_BATCH]
        log.info("  임베딩 배치 %d~%d ...", i + 1, i + len(batch))
        vecs = _call_embed_api(batch, base_url)
        results.extend(vecs)
    return results


def _build_records(
    rows: list[FaqRow],
    vecs: list[list[float]],
    lang: str,
    use_eng: bool,
) -> list[dict[str, Any]]:
    records = []
    for row, vec in zip(rows, vecs):
        content = (row.question_sample_eng or "") if use_eng else row.question_sample
        if not content.strip():
            continue
        records.append({
            "id": str(uuid.uuid4()),
            "faq_id": row.qna_code,
            "lang": lang,
            "content": content,
            "content_hash": _content_hash(content),
            "embedding_dim": len(vec),
            "embedding": str(vec),
            "model": _MODEL_ID,
        })
    return records


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main() -> None:
    dsn = _sync_dsn(settings.postgres_dsn)
    embed_url = settings.embedding_service_url

    if not (settings.openai_api_key or "").strip():
        log.error("OPENAI_API_KEY 가 설정되지 않았습니다. embedding/.env 를 확인하세요.")
        sys.exit(1)

    openai_client = OpenAI(api_key=settings.openai_api_key)

    log.info("DB 연결: %s", dsn.split("@")[-1])
    log.info("임베딩 서버: %s", embed_url)
    log.info("번역 모델: %s", settings.openai_model)
    log.info("임베딩 모델: %s", _MODEL_ID)

    with psycopg.connect(dsn) as conn:
        rows = fetch_faq_rows(conn)
        log.info("FAQ 행 %d개 로드 완료.", len(rows))

        # 1) 번역
        rows = run_translation(openai_client, rows)

        updates = [
            (r.question_sample_eng or "", r.answer_sample_eng or "", r.qna_code)
            for r in rows
            if r.question_sample_eng
        ]
        if updates:
            save_translations(conn, updates)
            log.info("번역 저장 완료 (%d행).", len(updates))

        # 2) 임베딩
        run_embedding(conn, rows, embed_url)

    log.info("FAQ 임베딩 파이프라인 완료.")


if __name__ == "__main__":
    main()
