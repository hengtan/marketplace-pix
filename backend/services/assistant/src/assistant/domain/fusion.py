from collections import defaultdict
from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]],
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[str, float]]:
    """Merges several ranked lists of ids. Each list contributes weight / (k + rank) per id,
    ranks starting at 1 and weights defaulting to 1. Ties are broken by first appearance."""
    if weights is not None and len(weights) != len(rankings):
        raise ValueError("one weight per ranking is required")
    scores: dict[str, float] = defaultdict(float)
    first_seen: dict[str, int] = {}
    for index, ranking in enumerate(rankings):
        weight = 1.0 if weights is None else weights[index]
        for position, item in enumerate(ranking, start=1):
            scores[item] += weight / (k + position)
            first_seen.setdefault(item, len(first_seen))
    return sorted(scores.items(), key=lambda pair: (-pair[1], first_seen[pair[0]]))
