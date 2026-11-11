import logging
import re
from dataclasses import dataclass, field

from assistant.application.ports import ChunkStore, Embedder, Reranker
from assistant.domain.filters import FilterParser
from assistant.domain.fusion import reciprocal_rank_fusion
from assistant.domain.models import Filters, Passage
from assistant.domain.text import content_tokens

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalConfig:
    branch_limit: int = 20
    candidates: int = 10
    final: int = 4
    rrf_k: int = 60
    min_score: float = 0.1


@dataclass(frozen=True)
class RetrievalResult:
    passages: list[Passage]
    filters: Filters
    query: str
    mode: str
    candidates: list[Passage] = field(default_factory=list)


class HybridRetriever:
    def __init__(
        self,
        store: ChunkStore,
        embedder: Embedder,
        reranker: Reranker,
        config: RetrievalConfig | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._reranker = reranker
        self._config = config or RetrievalConfig()

    async def retrieve(self, question: str, restrict: Filters | None = None) -> RetrievalResult:
        cfg = self._config
        name = self._embedder.name
        parser = FilterParser(await self._store.categories(name))
        query = parser.parse(question)
        parsed, residual, sort = query.filters, query.text, query.sort
        filters = Filters(
            max_price_cents=parsed.max_price_cents,
            min_price_cents=parsed.min_price_cents,
            category=parsed.category,
            product_ids=restrict.product_ids if restrict else None,
        )
        tokens = content_tokens(residual)

        if not tokens:
            if filters.is_empty and sort is None:
                return RetrievalResult([], filters, residual, "empty")
            browsed = await self._store.browse(name, filters, sort, cfg.branch_limit)
            top = _one_per_product(
                [p.with_score(round(p.rating / 5, 4), "browse") for p in browsed]
            )[: cfg.final]
            return RetrievalResult(top, filters, residual, "browse", top)

        query_text = " ".join(tokens)
        vector = (await self._embedder.embed([query_text]))[0]
        vector_hits = await self._store.vector_search(vector, name, filters, cfg.branch_limit)
        text_hits = await self._store.text_search(query_text, name, filters, cfg.branch_limit)

        by_id = {p.chunk_id: p for p in [*vector_hits, *text_hits]}
        fused = reciprocal_rank_fusion(
            [[p.chunk_id for p in vector_hits], [p.chunk_id for p in text_hits]], cfg.rrf_k
        )
        ordered = [by_id[cid].with_score(score, "fusion") for cid, score in fused]
        candidates = _one_per_product(ordered)[: cfg.candidates]
        reranked = self._reranker.rerank(query_text, candidates, cfg.final)
        final = [p for p in reranked if p.score >= cfg.min_score]
        if sort == "price_asc":
            final.sort(key=lambda p: (p.price_cents, -p.rating))
        elif sort == "rating_desc":
            final.sort(key=lambda p: (-p.rating, p.price_cents))
        logger.info(
            "retrieval vector=%d text=%d candidates=%d final=%d filters=%s",
            len(vector_hits),
            len(text_hits),
            len(candidates),
            len(final),
            filters.to_dict(),
        )
        return RetrievalResult(final, filters, residual, "hybrid", candidates)


def _one_per_product(passages: list[Passage]) -> list[Passage]:
    seen: set[object] = set()
    unique: list[Passage] = []
    for passage in passages:
        if passage.product_id not in seen:
            seen.add(passage.product_id)
            unique.append(passage)
    return unique


_SAFE_TERM = re.compile(r"[^a-z0-9]")


def to_tsquery_terms(query: str) -> str:
    terms = [_SAFE_TERM.sub("", tok) for tok in content_tokens(query)]
    return " | ".join(t for t in terms if t)
