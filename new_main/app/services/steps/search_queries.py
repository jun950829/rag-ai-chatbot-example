"""RAG용 검색 쿼리 목록. 짧거나 휴리스틱으로 축이 안 잡히면 LLM으로 3~5개 생성."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.steps.intent import heuristic_intent


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        t = (x or "").strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _fallback_queries(user_query: str, *, n_min: int, n_max: int, language: str = "ko") -> list[str]:
    q = user_query.strip()
    if (language or "").strip().lower() == "en":
        seeds = [
            q,
            f"{q} exhibitor booth",
            f"{q} exhibit product",
            f"{q} company profile",
            f"{q} exhibit item specification",
        ]
    else:
        seeds = [
            q,
            f"{q} 참가업체 부스",
            f"{q} 전시 제품",
            f"{q} 업체 소개 프로필",
            f"{q} exhibit item specification",
        ]
    merged = _dedupe_keep_order(seeds)
    pad = 0
    out = list(merged)
    while len(out) < n_min and pad < 12:
        pad += 1
        out = _dedupe_keep_order(out + [f"{q} (검색 변형 {pad})"])
    return out[:n_max]


def _should_expand_queries(normalized: str, *, short_chars: int) -> bool:
    q = normalized.strip()
    if len(q) < 2:
        return False
    if len(q) < short_chars:
        return True
    return heuristic_intent(q) is None


async def _expand_queries_llm(
    user_query: str, intent: str, *, n_min: int, n_max: int, language: str = "ko"
) -> list[str] | None:
    st = get_settings()
    if not st.retrieval_expand_queries_use_openai or not (st.openai_api_key or "").strip():
        return None
    client_kwargs: dict[str, str] = {"api_key": (st.openai_api_key or "").strip()}
    if (st.openai_base_url or "").strip():
        client_kwargs["base_url"] = (st.openai_base_url or "").strip()
    client = AsyncOpenAI(**client_kwargs)
    lang = (language or "ko").strip().lower()
    if lang == "en":
        system = (
            "You are a trade-show RAG search query generator. Given the user's question, "
            f"create {n_min}–{n_max} short, non-overlapping search queries to find exhibitors and exhibit items "
            "in a vector DB.\n"
            'Output exactly one JSON object: {"queries":["...","..."]}\n'
            "Write queries in English (Korean product/company names may be kept as-is).\n"
            f"Classification hint: intent={intent!r}."
        )
    else:
        system = (
            "너는 전시회 RAG 검색용 쿼리 생성기다. 사용자 질문을 벡터 DB(참가업체·전시품 청크)에서 잘 찾도록 "
            f"서로 겹치지 않게 {n_min}~{n_max}개의 짧은 검색 문장을 만든다.\n"
            '반드시 JSON 한 덩어리만 출력: {"queries":["...","..."]}\n'
            "언어: 한국어 위주(필요 시 영어 키워드 1~2개 혼용 가능).\n"
            f"분류 힌트 intent={intent!r} (company_query면 업체·부스, product_query면 제품·전시품 쪽 표현을 섞어도 됨)."
        )
    user = f"사용자 질문:\n{user_query.strip()}"
    try:
        resp = await client.chat.completions.create(
            model=st.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        raw = (resp.choices[0].message.content or "").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            data: Any = json.loads(raw[start : end + 1])
        else:
            data = json.loads(raw)
        arr = data.get("queries") if isinstance(data, dict) else None
        if not isinstance(arr, list):
            return None
        qs = [str(x).strip() for x in arr if str(x).strip()]
        qs = _dedupe_keep_order(qs)
        if len(qs) < n_min:
            return None
        return qs[:n_max]
    except Exception:
        return None


async def plan_retrieval_search_queries(normalized: str, intent: str, language: str = "ko") -> list[str]:
    """단일 쿼리 또는 3~5개 다중 쿼리(애매·짧은 입력 시)."""
    st = get_settings()
    n_max = max(1, st.retrieval_multiquery_max)
    n_min = min(max(1, st.retrieval_multiquery_min), n_max)
    short_chars = max(8, st.retrieval_multiquery_short_chars)
    base = normalized.strip()
    if not base:
        return []
    if not _should_expand_queries(normalized, short_chars=short_chars):
        return [base]
    llm_qs = await _expand_queries_llm(base, intent, n_min=n_min, n_max=n_max, language=language)
    if llm_qs and len(llm_qs) >= n_min:
        return llm_qs[:n_max]
    return _fallback_queries(base, n_min=n_min, n_max=n_max, language=language)
