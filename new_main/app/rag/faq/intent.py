"""FAQ 전용 의도 분류.

chat pipeline 의 intent(company_query/product_query/chat)와 별개로,
FAQ 질문에서 qa_user(visitor/exhibitor)를 분류한다.
"""

from __future__ import annotations

_VISITOR_HINTS = (
    "참관객", "관람객", "방문자", "관람", "입장", "방문",
    "visitor", "attendee", "참관",
)
_EXHIBITOR_HINTS = (
    "참가업체", "참가사", "참가 업체", "출품사", "참가자",
    "exhibitor", "부스 신청", "참가 신청",
)


def classify_faq_qa_user(query: str) -> str | None:
    """visitor / exhibitor / None(불명확) 반환."""
    q = (query or "").lower()
    v = sum(1 for h in _VISITOR_HINTS if h.lower() in q)
    e = sum(1 for h in _EXHIBITOR_HINTS if h.lower() in q)
    if v > e:
        return "visitor"
    if e > v:
        return "exhibitor"
    return None
