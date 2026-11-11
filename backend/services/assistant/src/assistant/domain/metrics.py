import math
from collections.abc import Collection, Mapping, Sequence


def hit_at_k(
    ranked: Sequence[str], relevant: Collection[str], k: int, require_all: bool = False
) -> bool:
    top = set(ranked[:k])
    if not relevant:
        return False
    return set(relevant) <= top if require_all else bool(set(relevant) & top)


def reciprocal_rank(ranked: Sequence[str], relevant: Collection[str]) -> float:
    for rank, item in enumerate(ranked, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked: Sequence[str], gains: Mapping[str, float], k: int) -> float:
    dcg = sum(gains.get(item, 0.0) / math.log2(rank + 1) for rank, item in enumerate(ranked[:k], 1))
    ideal = sorted(gains.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(rank + 1) for rank, g in enumerate(ideal, 1))
    return dcg / idcg if idcg else 0.0


def context_precision(ranked: Sequence[str], relevant: Collection[str]) -> float:
    """Average precision over the retrieved context: relevant items near the top score higher."""
    found = 0
    total = 0.0
    for rank, item in enumerate(ranked, start=1):
        if item in relevant:
            found += 1
            total += found / rank
    return total / found if found else 0.0


def context_recall(ranked: Sequence[str], relevant: Collection[str], cap: int) -> float:
    if not relevant:
        return 0.0
    wanted = min(len(relevant), cap)
    return min(len(set(ranked) & set(relevant)), wanted) / wanted
