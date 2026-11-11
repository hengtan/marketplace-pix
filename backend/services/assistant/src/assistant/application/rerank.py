from collections.abc import Sequence

from assistant.domain.models import Passage
from assistant.domain.text import content_tokens, stem


def _stems(text: str) -> set[str]:
    return {stem(tok) for tok in content_tokens(text)}


class LexicalReranker:
    """Reorders fused candidates by how much of the question the passage actually covers.
    Passages with no lexical overlap with the question get score 0 and can be dropped
    by the caller: that is what turns 'nothing relevant' into an honest 'not found'."""

    def rerank(self, query: str, candidates: Sequence[Passage], limit: int) -> list[Passage]:
        query_stems = _stems(query)
        if not query_stems or not candidates:
            return []
        total = len(candidates)
        scored: list[tuple[float, int, Passage]] = []
        for position, passage in enumerate(candidates):
            body_stems = _stems(passage.content)
            name_stems = _stems(passage.name)
            coverage = len(query_stems & body_stems) / len(query_stems)
            name_coverage = len(query_stems & name_stems) / len(query_stems)
            prior = (total - position) / total
            score = 0.0 if coverage == 0 else 0.6 * coverage + 0.25 * name_coverage + 0.15 * prior
            scored.append((score, position, passage))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [p.with_score(round(s, 4), "rerank") for s, _, p in scored[:limit]]
