from __future__ import annotations

import re
from collections import deque

_COMPANY_SUFFIX_RE = r"(글로벌|테크|전자|헬스|메디칼|메디컬|inc|corp|ltd|co|co\.)"
_COMPANY_TOKEN_RE = re.compile(
    rf"([가-힣A-Za-z0-9][가-힣A-Za-z0-9&().\-]{{1,30}}{_COMPANY_SUFFIX_RE}?)(?:\s*\(|\s|$)",
    re.IGNORECASE,
)


def extract_company_entities(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for match in _COMPANY_TOKEN_RE.finditer(raw):
        token = match.group(1).strip(" ,.!?\"'()[]{}")
        if len(token) < 2:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


class ConversationMemory:
    def __init__(self, max_turns: int = 5):
        self.max_turns = max_turns
        self._messages: deque[dict[str, str]] = deque(maxlen=max_turns * 2)
        self._entities: set[str] = set()

    def add(self, role: str, message: str) -> None:
        item = {"role": role, "message": message}
        self._messages.append(item)
        if role == "assistant":
            for entity in extract_company_entities(message):
                self._entities.add(entity.lower())

    def get_recent(self) -> list[dict[str, str]]:
        return list(self._messages)

    def last_assistant_message(self) -> str:
        for msg in reversed(self._messages):
            if msg.get("role") == "assistant":
                return msg.get("message", "")
        return ""

    def has_entity(self, query: str) -> bool:
        q = (query or "").lower()
        if not q:
            return False
        return any(entity in q for entity in self._entities)

