import math
from collections.abc import Mapping, Sequence


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def mmr_select(
    relevance: Mapping[str, float],
    vectors: Mapping[str, Sequence[float]],
    k: int,
    lambda_: float = 0.7,
) -> list[str]:
    """Maximal Marginal Relevance: greedily picks the item with the best
    lambda * relevance - (1 - lambda) * similarity to what was already picked."""
    if not 0.0 <= lambda_ <= 1.0:
        raise ValueError("lambda must be between 0 and 1")
    remaining = list(relevance)
    selected: list[str] = []
    while remaining and len(selected) < k:

        def marginal(item: str) -> float:
            redundancy = max(
                (
                    cosine(vectors[item], vectors[chosen])
                    for chosen in selected
                    if item in vectors and chosen in vectors
                ),
                default=0.0,
            )
            return lambda_ * relevance[item] - (1 - lambda_) * redundancy

        best = max(remaining, key=lambda item: (marginal(item), relevance[item]))
        selected.append(best)
        remaining.remove(best)
    return selected
