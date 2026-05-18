"""후속 질문·카드 클릭 유도 등 추천 문구 (UI 버튼용)."""

from __future__ import annotations


def rag_followups_from_context(*, query: str, intent: str, cards: list[dict[str, object]] | None) -> list[dict[str, str]]:
    """일반 질문도 FAQ와 같은 follow-up 버튼 UI를 붙이기 위한 기본 followups."""
    title = ""
    if isinstance(cards, list) and cards:
        title = str((cards[0] or {}).get("title") or "").strip()
    subj = title or (query or "").strip()
    if intent in {"company"}:
        return [
            {"label": "부스 위치", "ask": f"{subj} 부스 위치 알려줘"},
            {"label": "연락처", "ask": f"{subj} 담당자 연락처/이메일 알려줘"},
            {"label": "대표 제품", "ask": f"{subj} 대표 제품(전시품) 3개 알려줘"},
            {"label": "상세 소개", "ask": f"{subj} 회사 소개를 더 자세히 알려줘"},
        ]
    if intent in {"product"}:
        return [
            {"label": "제조사/업체", "ask": f"{subj} 제조사/참가업체가 어디야?"},
            {"label": "스펙", "ask": f"{subj} 주요 스펙/특징 정리해줘"},
            {"label": "가격/구매", "ask": f"{subj} 가격대나 구매/문의 방법 알려줘"},
            {"label": "비교", "ask": f"{subj} 비슷한 제품 3개와 차이점 비교해줘"},
        ]
    return [
        {"label": "핵심 요약", "ask": f"{subj} 핵심만 요약해줘"},
        {"label": "관련 항목", "ask": f"{subj} 관련 업체/제품 더 찾아줘"},
        {"label": "조건 추가", "ask": f"{subj} 조건을 넣어서 다시 찾아줘"},
    ]
