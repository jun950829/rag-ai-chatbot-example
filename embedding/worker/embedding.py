import hashlib
from typing import Iterable


def _pseudo_embedding(text: str, dim: int = 1024) -> list[float]:
    """
    데모용 임베딩 함수.
    운영 시 sentence-transformers/OpenAI embedding 모델 호출로 교체한다.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    base = [b / 255.0 for b in digest]
    values = (base * ((dim // len(base)) + 1))[:dim]
    return values


def build_embeddings_batch(chunks: Iterable[str]) -> list[list[float]]:
    # 배치 단위로 한 번에 임베딩 계산하여 처리량을 높인다.
    return [_pseudo_embedding(chunk) for chunk in chunks]
