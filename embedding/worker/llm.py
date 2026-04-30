import asyncio
import re


async def stream_llm_tokens(prompt: str):
    """
    실제 운영에서는 OpenAI/사내 LLM SDK 스트림 호출로 교체한다.
    여기서는 논블로킹 동작 예시를 위해 토큰을 비동기 생성한다.
    """
    words = ["요청을", "처리했고,", "아래는", "생성된", "응답입니다.", prompt]
    for token in words:
        await asyncio.sleep(0.12)
        yield token


_FOLLOWUP_RE = re.compile(
    r"(어떤\s*(업체|회사|기업)|어떤\s*곳|무슨\s*(업체|회사)|자세히|더\s*알려|추가로|특징|강점|약점|"
    r"[가-힣a-zA-Z0-9&().\-_/]+(은|는|이|가)?\s*(어디|어딘|위치|뭐|뭔데|어떤|who|what|where))",
    re.IGNORECASE,
)


def classify_intent_heuristic(message: str, *, previous_intent: str | None = None) -> str:
    text = (message or "").strip().lower()
    if not text:
        return "not_related"

    greeting_words = ("안녕", "안녕하세요", "hello", "hi", "hey")
    followup_starts = ("그럼", "그리고", "그 회사", "그 업체", "then", "also", "what about")
    not_related_words = ("날씨", "주식", "환율", "운세", "점심", "movie", "recipe")
    company_words = ("회사", "업체", "기업", "참가", "전시", "부스", "exhibitor", "company", "booth")
    product_words = ("전시품", "제품", "상품", "아이템", "product", "item", "model", "모델")

    if any(w in text for w in greeting_words):
        return "greeting"
    # 직전이 업체 검색 맥락이면 follow-up 패턴을 우선적으로 본다.
    if (previous_intent or "").strip() in {"company", "product", "follow_up"} and _FOLLOWUP_RE.search(text):
        return "follow_up"
    if text.startswith(followup_starts):
        return "follow_up"
    if any(w in text for w in not_related_words):
        return "not_related"
    if any(w in text for w in product_words):
        return "product"
    if any(w in text for w in company_words):
        return "company"
    return "general"


async def stream_text_tokens(text: str):
    """줄바꿈을 유지하면서 짧은 덩어리로 스트리밍 (단어 단위 split은 \\n을 깨뜨림)."""
    t = text or ""
    step = 56
    for i in range(0, len(t), step):
        yield t[i : i + step]
        await asyncio.sleep(0.022)
