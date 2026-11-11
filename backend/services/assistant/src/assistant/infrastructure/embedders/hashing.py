import hashlib
import math
from collections.abc import Sequence

from assistant.domain.text import content_tokens, stem


class HashingEmbedder:
    """Feature hashing of words, rough stems and word bigrams into a fixed-size signed vector,
    L2-normalized. No model and no training: similarity is purely lexical, but deterministic
    and good enough to exercise the whole retrieval pipeline."""

    def __init__(self, dimension: int = 256) -> None:
        if dimension < 8:
            raise ValueError("dimension must be at least 8")
        self._dimension = dimension

    @property
    def name(self) -> str:
        return f"hashing-{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed_one(text) for text in texts]

    def embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        tokens = content_tokens(text)
        for token in tokens:
            self._add(vector, f"w:{token}", 1.0)
            stemmed = stem(token)
            if stemmed != token:
                self._add(vector, f"s:{stemmed}", 0.5)
        for left, right in zip(tokens, tokens[1:], strict=False):
            self._add(vector, f"b:{left} {right}", 0.7)
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]

    def _add(self, vector: list[float], feature: str, weight: float) -> None:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        index = value % self._dimension
        sign = 1.0 if (value >> 40) & 1 else -1.0
        vector[index] += sign * weight
