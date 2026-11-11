from collections.abc import Sequence

from assistant.domain.models import Passage
from assistant.domain.text import content_tokens, stem

EXTRA_WEIGHT = 0.5


def _stems(text: str) -> set[str]:
    return {stem(tok) for tok in content_tokens(text)}


class LexicalReranker:
    """Reorders fused candidates by how much of the question the passage actually covers.
    Passages with no lexical overlap with the question get score 0 and can be dropped
    by the caller: that is what turns 'nothing relevant' into an honest 'not found'.
    Terms added by query expansion count for half of an original term."""

    def rerank(
        self,
        query: str,
        candidates: Sequence[Passage],
        limit: int,
        extra_terms: Sequence[str] = (),
    ) -> list[Passage]:
        query_stems = _stems(query)
        extra_stems = {stem(t) for t in extra_terms} - query_stems
        if not query_stems or not candidates:
            return []
        total = len(candidates)
        scored: list[tuple[float, int, Passage]] = []
        for position, passage in enumerate(candidates):
            body_stems = _stems(passage.content)
            name_stems = _stems(passage.name)
            coverage = self._coverage(query_stems, extra_stems, body_stems)
            name_coverage = self._coverage(query_stems, extra_stems, name_stems)
            prior = (total - position) / total
            score = 0.0 if coverage == 0 else 0.6 * coverage + 0.25 * name_coverage + 0.15 * prior
            scored.append((score, position, passage))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [p.with_score(round(s, 4), "rerank") for s, _, p in scored[:limit]]

    @staticmethod
    def _coverage(query: set[str], extra: set[str], body: set[str]) -> float:
        weighted = len(query & body) + EXTRA_WEIGHT * len(extra & body)
        return min(1.0, weighted / len(query))
