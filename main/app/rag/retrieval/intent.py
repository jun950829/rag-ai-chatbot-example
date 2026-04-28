from __future__ import annotations

import re
from typing import Any

from app.rag.retrieval.memory import ConversationMemory

# 검색 의도는 더 이상 new_company가 아니라 company/product로 분기한다.
INTENT_LABELS = {"greeting", "followup", "company", "product", "general", "not_related"}
LANGUAGE_LABELS = {"ko", "en"}

_KOREAN_RE = re.compile(r"[가-힣]")
_ENGLISH_RE = re.compile(r"[A-Za-z]")
_GENERIC_REQUEST_PATTERNS = (
    r"\bshow\b",
    r"\bshow me\b",
    r"\bfind\b",
    r"\blist\b",
    r"\brecommend\b",
    r"\bdetails?\b",
    r"\babout\b",
    r"보여\s*줘",
    r"알려\s*줘",
    r"추천\s*해\s*줘",
    r"찾아\s*줘",
)
_GREETING_WORDS = ("안녕", "안녕하세요", "반가워", "hello", "hi", "hey")
_NOT_RELATED_HINTS = ("날씨", "주가", "환율", "점심", "sports", "bitcoin", "movie", "recipe")
_COMPANY_HINTS = (
    "업체",
    "회사",
    "기업",
    "참가",
    "참가업체",
    "전시",
    "부스",
    "company",
    "exhibitor",
    "booth",
    "hall",
    "profile",
)
_PRODUCT_HINTS = (
    "전시품",
    "제품",
    "상품",
    "품목",
    "아이템",
    "product",
    "item",
    "exhibit item",
    "model",
    "모델",
    "스펙",
)
_FOLLOWUP_STARTS = ("그럼", "그리고", "또", "추가로", "then", "also")
_FOLLOWUP_PRONOUNS = ("그거", "그 회사", "그 업체", "걔", "it", "that")
_FOLLOWUP_QUESTION_WORDS = ("어디", "뭐", "뭔데", "어떤", "who", "what")


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_language(query: str) -> str:
    text = (query or "").strip()
    kor_count = len(_KOREAN_RE.findall(text))
    eng_count = len(_ENGLISH_RE.findall(text))
    return "ko" if kor_count >= eng_count else "en"


def _strip_request_scaffolding(raw: str) -> str:
    text = _norm_text(raw)
    for pattern in _GENERIC_REQUEST_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(회사|업체|기업|company|product|제품)\b", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _is_informative_query(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2:
        return False
    return bool(_KOREAN_RE.search(t) or _ENGLISH_RE.search(t))


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def _is_followup_query(text: str, *, has_history: bool, memory: ConversationMemory | None) -> tuple[bool, str]:
    # (A) vague short query + history
    if has_history and len(text) <= 15:
        return True, "short_with_history"
    # (B) entity match from memory
    if memory is not None and memory.has_entity(text):
        return True, "entity_match_from_memory"
    # (C) short question pattern
    if len(text) <= 20 and any(word in text for word in _FOLLOWUP_QUESTION_WORDS):
        return True, "short_question"
    # (D) pronoun-based follow-up
    if any(token in text for token in _FOLLOWUP_PRONOUNS):
        return True, "pronoun_based"
    # (E) continuation words
    if text.startswith(_FOLLOWUP_STARTS):
        return True, "continuation_prefix"
    return False, ""


def _looks_like_greeting(text: str) -> bool:
    return any(word in text for word in _GREETING_WORDS)


async def classify_intent_v2(
    *,
    message: str,
    has_history: bool,
    openai_client: Any | None,
    model: str = "gpt-4o-mini",
    memory: ConversationMemory | None = None,
) -> tuple[str, dict[str, Any]]:
    n = _norm_text(message)
    if _looks_like_greeting(n):
        return "greeting", {"source": "heuristic_greeting"}

    is_followup, reason = _is_followup_query(n, has_history=has_history, memory=memory)
    if is_followup:
        return "followup", {"source": f"heuristic_followup_{reason}"}

    if any(word in n for word in _NOT_RELATED_HINTS):
        return "not_related", {"source": "heuristic_not_related"}
    # product/company는 키워드로 우선 분기한다. (둘 다 걸리면 product를 우선)
    if any(word in n for word in _PRODUCT_HINTS):
        return "product", {"source": "heuristic_product"}
    if any(word in n for word in _COMPANY_HINTS):
        return "company", {"source": "heuristic_company"}

    # 애매하면 LLM fallback (요구사항: general/애매한 경우에만 사용)
    if openai_client is not None:
        try:
            resp = await openai_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "너는 전시 RAG 시스템의 intent classifier다.\n"
                            "가능한 라벨은: company, product, followup, general, not_related.\n"
                            "반드시 라벨 한 단어만 출력해라."
                        ),
                    },
                    {"role": "user", "content": f"질문: {message}\n라벨만 출력:"},
                ],
            )
            out = ((resp.choices[0].message.content) or "").strip().lower()
            if out in INTENT_LABELS:
                return out, {"source": "openai_fallback", "model": model}
        except Exception:
            # fallback 실패는 general로 처리 (성능/안정성 우선)
            pass

    return "general", {"source": "heuristic_general"}


def _intent_meta_used_openai(intent_meta: dict[str, Any]) -> bool:
    return str(intent_meta.get("source", "")).startswith("openai")


def build_intent_heuristic_answer(*, intent: str, language: str, query: str) -> str:
    q = (query or "").strip()
    if intent == "greeting":
        if language == "ko":
            return "안녕하세요. 전시 참가업체 검색 도우미입니다. 찾고 싶은 제품, 기술, 업체명, 부스 정보 중 하나를 입력해 주세요."
        return "Hello. I am your exhibitor search assistant. Please tell me a product, technology, company name, or booth detail to search."
    if intent == "not_related":
        if language == "ko":
            return f"입력하신 질문('{q}')은 전시 참가업체 검색 범위와 거리가 있습니다. 업체명, 제품/기술 키워드, 국가, 전시홀, 부스번호 중심으로 다시 질문해 주세요."
        return f"Your query ('{q}') appears to be outside exhibitor search scope. Please ask with company name, product/technology, country, hall, or booth number."
    if intent == "general":
        if language == "ko":
            return "테스트/일반 대화로 이해했습니다. 업체 검색을 원하면 제품/기술 키워드나 업체명, 부스 정보로 질문해 주세요."
        return "I understood this as a general conversation message. If you want exhibitor search, please include product keyword, company name, or booth detail."
    return ""


__all__ = [
    "INTENT_LABELS",
    "LANGUAGE_LABELS",
    "_intent_meta_used_openai",
    "_norm_text",
    "_strip_request_scaffolding",
    "_is_informative_query",
    "_dedupe_keep_order",
    "classify_intent_v2",
    "detect_language",
    "build_intent_heuristic_answer",
]
