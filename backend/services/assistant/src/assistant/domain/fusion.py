from collections import defaultdict
from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], k: int = 60
) -> list[tuple[str, float]]:
    """Merges several ranked lists of ids. Each list contributes 1 / (k + rank) per id,
    ranks starting at 1. Ties are broken by the order of first appearance."""
    scores: dict[str, float] = defaultdict(float)
    first_seen: dict[str, int] = {}
    for ranking in rankings:
        for position, item in enumerate(ranking, start=1):
            scores[item] += 1.0 / (k + position)
            first_seen.setdefault(item, len(first_seen))
    return sorted(scores.items(), key=lambda pair: (-pair[1], first_seen[pair[0]]))
