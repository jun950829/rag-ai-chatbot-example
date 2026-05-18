"""출처·인용 문구 정책 (향후 citation 전용 LLM 단계에서 확장)."""

# 현재는 검색 결과 포맷이 ``format_search_results_for_llm_context`` 에서 처리된다.
CITATION_POLICY_KO = (
    "답변에 근거가 되는 사실은 제공된 참고 자료 안에서만 서술하고, "
    "출처 번호나 내부 ID는 사용자에게 노출하지 않는다."
)

CITATION_POLICY_EN = (
    "Ground every factual claim in the provided reference only; "
    "do not expose internal IDs, scores, or raw retrieval metadata to the user."
)
