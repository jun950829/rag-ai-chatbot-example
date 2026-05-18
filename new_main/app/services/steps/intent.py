from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings

# 휴리스틱: 명확할 때만 라벨 확정 (나머지는 LLM 또는 chat)
_GREETING_PATTERNS = (
    "안녕",
    "하이",
    "헬로",
    "반가",
    "안녕하세요",
    "hello",
    "hi",
    "hey",
    "good morning",
    "good afternoon",
    "good evening",
)

_COMPANY_HINTS = (
    "참가기업",
    "참가사",
    "참가 업체",
    "업체",
    "회사",
    "주식회사",
    "㈜",
    "부스",
    "exhibitor",
    "vendor",
    "기업",
    "전시회사",
)
_PRODUCT_HINTS = (
    "제품",
    "전시품",
    "솔루션",
    "디바이스",
    "장비",
    "product",
    "item",
    "카탈로그",
    "모델",
)


def _heuristic_intent(query: str) -> str | None:
    q = (query or "").strip()
    if not q:
        return "empty"
    lower = q.lower()

    # 짧은 인사/감탄 등은 검색 없이 일반 대화로 처리
    if len(q) <= 20:
        for g in _GREETING_PATTERNS:
            if g.lower() in lower:
                return "greeting"

    c = sum(1 for h in _COMPANY_HINTS if h.lower() in lower or h in q)
    p = sum(1 for h in _PRODUCT_HINTS if h.lower() in lower or h in q)
    if c > 0 and p == 0:
        return "company_query"
    if p > 0 and c == 0:
        return "product_query"
    if c > 0 and p > 0:
        return "company_query"
    return None


async def _llm_classify_intent(query: str) -> str | None:
    st = get_settings()
    if not st.intent_use_openai or not (st.openai_api_key or "").strip():
        return None
    client_kwargs: dict[str, str] = {"api_key": (st.openai_api_key or "").strip()}
    if (st.openai_base_url or "").strip():
        client_kwargs["base_url"] = (st.openai_base_url or "").strip()
    client = AsyncOpenAI(**client_kwargs)
    system = (
        "너는 전시회 챗봇 라우터다. 사용자 질문을 아래 중 하나로만 분류해 JSON 한 줄로 답한다.\n"
        '형식: {"intent":"..."}\n'
        "허용 intent 값:\n"
        "- greeting: 인사/감사/짧은 감탄(안녕, hi, 감사합니다 등) — DB 검색 불필요\n"
        "- company_query: 참가업체/회사/부스/참가사를 찾거나 비교·추천\n"
        "- product_query: 제품·전시품·솔루션·장비·모델 등을 찾거나 비교\n"
        "- chat: 위에 해당하지 않거나 애매함(일반 대화·혼합 검색은 chat)\n"
        "운영 FAQ만 있는 질문도 chat으로 둔다(별도 FAQ 파이프라인이 있을 수 있음)."
    )
    user = f"질문: {query.strip()}"
    try:
        resp = await client.chat.completions.create(
            model=st.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            max_tokens=80,
        )
        raw = (resp.choices[0].message.content or "").strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            data = json.loads(raw[start : end + 1])
        else:
            data = json.loads(raw)
        label = str(data.get("intent") or "").strip().lower()
        if label in ("greeting", "company_query", "product_query", "chat"):
            return label
    except Exception:
        return None
    return None


def heuristic_intent(query: str) -> str | None:
    """참가기업/제품 키워드 휴리스틱. 축이 안 보이면 ``None`` (검색 쿼리 확장 판단에 사용)."""
    return _heuristic_intent(query)


# FAQ no_match → 카탈로그 전환 UI (영문은 단어 product/company 만으로는 판정하지 않음)
_FAQ_POLICY_EN = re.compile(
    r"\b(how|what|when|where|why|can|could|may|should|is|are|do|does|did)\b",
    re.I,
)
_FAQ_POLICY_EN_TAIL = re.compile(
    r"\b(allow|allowed|rule|rules|policy|registration|register|deadline|hours?|parking|fee|cost|bring|bringing)\b",
    re.I,
)
_EN_SEARCH_VERBS = re.compile(
    r"\b(find|search|show|list|lookup|recommend|looking\s+for|need)\b",
    re.I,
)
_EN_COMPANY_PHRASES = (
    "exhibitor",
    "booth number",
    "booth location",
    "booth",
    "vendor",
    "company name",
    "company info",
    "company information",
    "about the company",
    "participating company",
)
_EN_PRODUCT_PHRASES = (
    "exhibit item",
    "exhibit product",
    "product catalog",
    "product list",
    "product search",
    "show me products",
    "find product",
    "search product",
)


def heuristic_catalog_redirect_intent(query: str, language: str) -> str | None:
    """FAQ 미매칭 시 제품/업체 검색 모드 전환 UI를 띄울지 판단.

    일반 ``heuristic_intent`` 와 달리 영문에서 ``product`` / ``item`` 단어만 포함된
    FAQ 성 질문(규정·허용 여부 등)은 ``None`` 으로 둔다.
    """
    q = (query or "").strip()
    if not q:
        return None
    lang = (language or "ko").strip().lower()

    if lang == "en":
        lower = q.lower()
        # FAQ 정책/절차 질문 (What products are allowed … 등)
        if _FAQ_POLICY_EN.search(lower) and _FAQ_POLICY_EN_TAIL.search(lower):
            return None
        if re.search(r"\bwhat\s+(is|are)\s+the\b", lower) and re.search(
            r"\b(product|item|rule|policy)\b", lower
        ):
            return None

        if _EN_SEARCH_VERBS.search(lower) and re.search(
            r"\b(products?|items?|exhibits?)\b", lower, re.I
        ):
            return "product_query"
        for phrase in _EN_PRODUCT_PHRASES:
            if phrase in lower:
                return "product_query"

        if _EN_SEARCH_VERBS.search(lower) and re.search(
            r"\b(company|companies|exhibitor|vendor|booth)\b", lower, re.I
        ):
            return "company_query"
        for phrase in _EN_COMPANY_PHRASES:
            if phrase in lower:
                return "company_query"
        if re.search(r"\bcompany\b", lower) and re.search(
            r"\b(info|information|details|about)\b", lower, re.I
        ):
            return "company_query"
        return None

    h = _heuristic_intent(q)
    if h in ("company_query", "product_query"):
        return h
    return None


async def classify_intent(query: str) -> str:
    """규칙 우선, 애매하면(및 설정 시) LLM으로 intent 보정."""
    h = _heuristic_intent(query)
    if h is not None and h not in ("empty",):
        return h
    if h == "empty":
        return "empty"
    llm = await _llm_classify_intent(query)
    if llm:
        return llm
    return "chat"


def resolve_early_exit(
    intent: str, normalized: str, language: str
) -> tuple[list[dict[str, Any]], AsyncIterator[str]] | None:
    """검색이 불필요한 intent(empty, greeting)이면 즉시 (cards, stream) 반환.

    검색이 필요한 intent이면 ``None`` 을 반환하여 파이프라인이 계속 진행하도록 한다.
    """
    if intent == "empty":
        async def _empty() -> AsyncIterator[str]:
            yield ("Please enter a question." if language == "en" else "질문을 입력해 주세요.")
        return [], _empty()

    if intent == "greeting":
        if language == "en":
            text = (
                "Hello, nice to meet you!\n\n"
                "I'm the exhibition guide assistant.\n\n"
                "Do you have a product or company name you'd like to look up?"
            )
        else:
            text = (
                "안녕하세요, 반갑습니다!\n\n"
                "저는 이번 전시회 안내 도우미예요.\n\n"
                "찾고 싶은 제품명이나 회사명이 있으신가요?"
            )

        async def _greeting() -> AsyncIterator[str]:
            yield text
        return [], _greeting()

    return None


# ── 리스트형 응답 판단 ───────────────────────────────────────────

_LIST_INTENTS = ("product_query", "company_query")
_LIST_MIN_CARDS = 3


def is_list_response(intent: str, cards_count: int) -> bool:
    """검색 의도 + 충분한 카드 → LLM 생략하고 짧은 안내만 반환할지 판단."""
    return intent in _LIST_INTENTS and cards_count >= _LIST_MIN_CARDS


def list_short_answer(intent: str, language: str) -> str:
    """리스트형 응답 시 카드 앞에 보여줄 짧은 안내 메시지."""
    lang = (language or "ko").strip().lower()
    if lang == "en":
        if intent == "product_query":
            return (
                "Here are the product results.\n"
                "Select an item to see detailed information."
            )
        return (
            "Here are the exhibitor results.\n"
            "Select a company to see detailed information."
        )
    if intent == "product_query":
        return (
            "다음과 같은 제품 리스트를 찾았습니다.\n"
            "관심 있는 항목을 선택하면 상세 정보를 안내해드릴게요."
        )
    return (
        "다음과 같은 참가업체 리스트를 찾았습니다.\n"
        "관심 있는 업체를 선택하면 상세 정보를 안내해드릴게요."
    )
