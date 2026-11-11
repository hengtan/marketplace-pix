import logging
import re
from dataclasses import dataclass, field, replace
from typing import Literal

from assistant.application.ports import ChunkStore, Embedder, Reranker
from assistant.application.understanding import (
    PlanOptions,
    QueryPart,
    QueryPlan,
    QueryUnderstanding,
)
from assistant.domain.chunking import merge_overlapping
from assistant.domain.diversity import mmr_select
from assistant.domain.fusion import reciprocal_rank_fusion
from assistant.domain.lexicon import SHOPPING_WORDS
from assistant.domain.models import Filters, Passage
from assistant.domain.text import content_tokens, normalize, stem

logger = logging.getLogger(__name__)

RewriteMode = Literal["off", "always", "adaptive"]


@dataclass(frozen=True)
class RetrievalConfig:
    branch_limit: int = 20
    candidates: int = 10
    final: int = 4
    rrf_k: int = 60
    min_score: float = 0.1
    relative_cutoff: float = 0.5
    vector_weight: float = 1.0
    text_weight: float = 1.0
    hyde_weight: float = 1.0
    rewrite: RewriteMode = "off"
    adaptive_threshold: float = 0.6
    typo_correction: bool = False
    hyde: bool = False
    decompose: bool = False
    negation: bool = False
    mmr: bool = False
    mmr_lambda: float = 0.7
    parent_documents: bool = False
    prefilter: bool = True

    def plan_options(self) -> PlanOptions:
        return PlanOptions(
            typo_correction=self.typo_correction,
            expand=self.rewrite != "off",
            hyde=self.hyde,
            decompose=self.decompose,
            negation=self.negation,
        )


@dataclass(frozen=True)
class RetrievalResult:
    passages: list[Passage]
    filters: Filters
    query: str
    mode: str
    candidates: list[Passage] = field(default_factory=list)
    plan: QueryPlan | None = None


class HybridRetriever:
    def __init__(
        self,
        store: ChunkStore,
        embedder: Embedder,
        reranker: Reranker,
        config: RetrievalConfig | None = None,
        understanding: QueryUnderstanding | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._reranker = reranker
        self._config = config or RetrievalConfig()
        self._understanding = understanding or QueryUnderstanding(store, embedder.name)

    @property
    def config(self) -> RetrievalConfig:
        return self._config

    @property
    def understanding(self) -> QueryUnderstanding:
        return self._understanding

    async def retrieve(self, question: str, restrict: Filters | None = None) -> RetrievalResult:
        cfg = self._config
        plan = await self._understanding.plan(question, cfg.plan_options())
        if len(plan.parts) == 1:
            result = await self._retrieve_part(plan.parts[0], restrict)
            return replace(result, plan=plan)

        per_part = max(1, cfg.final // len(plan.parts))
        merged: list[Passage] = []
        for part in plan.parts:
            sub = await self._retrieve_part(part, restrict)
            merged.extend(sub.passages[:per_part])
        unique = _one_per_product(merged)[: cfg.final]
        return RetrievalResult(unique, Filters(), question, "decomposed", unique, plan)

    async def _retrieve_part(self, part: QueryPart, restrict: Filters | None) -> RetrievalResult:
        cfg = self._config
        name = self._embedder.name
        filters = replace(part.filters, product_ids=restrict.product_ids if restrict else None)
        tokens = part.tokens
        if filters.product_ids:
            tokens = [t for t in tokens if t not in SHOPPING_WORDS]
            part = replace(part, tokens=tokens)
        residual = " ".join(tokens)

        if not tokens:
            if filters.is_empty and part.sort is None:
                return RetrievalResult([], filters, residual, "empty")
            browsed = await self._store.browse(name, filters, part.sort, cfg.branch_limit)
            top = _one_per_product(
                [p.with_score(round(p.rating / 5, 4), "browse") for p in browsed]
            )[: cfg.final]
            top = await self._expand_parents(self._exclude(top, part.exclusions))
            return RetrievalResult(top, filters, residual, "browse", top)

        direct = cfg.rewrite == "always" or (cfg.rewrite == "off" and cfg.hyde)
        if direct:
            ranked, candidates = await self._search(part, filters, part.expansions, part.hyde)
        else:
            ranked, candidates = await self._search(part, filters, [], None)
            weak = not ranked or ranked[0].score < cfg.adaptive_threshold
            if cfg.rewrite == "adaptive" and weak and (part.expansions or part.hyde):
                retry, retry_candidates = await self._search(
                    part, filters, part.expansions, part.hyde
                )
                if retry and (not ranked or retry[0].score > ranked[0].score):
                    ranked, candidates = retry, retry_candidates

        final = [p for p in ranked if p.score >= cfg.min_score]
        if final:
            floor = final[0].score * cfg.relative_cutoff
            final = [p for p in final if p.score >= floor]
        final = await self._diversify(final)
        final = await self._expand_parents(final)
        if part.sort == "price_asc":
            final.sort(key=lambda p: (p.price_cents, -p.rating))
        elif part.sort == "rating_desc":
            final.sort(key=lambda p: (-p.rating, p.price_cents))
        logger.info(
            "retrieval candidates=%d final=%d filters=%s", len(candidates), len(final), filters
        )
        return RetrievalResult(final, filters, residual, "hybrid", candidates)

    async def _search(
        self, part: QueryPart, filters: Filters, extras: list[str], hyde: str | None
    ) -> tuple[list[Passage], list[Passage]]:
        cfg = self._config
        name = self._embedder.name
        search_filters = filters if cfg.prefilter else Filters(product_ids=filters.product_ids)
        base_text = " ".join(part.tokens)
        query_text = " ".join([*part.tokens, *extras])
        vector = (await self._embedder.embed([query_text]))[0]
        vector_hits = await self._store.vector_search(
            vector, name, search_filters, cfg.branch_limit
        )
        text_hits = await self._store.text_search(
            query_text, name, search_filters, cfg.branch_limit
        )
        rankings = [[p.chunk_id for p in vector_hits], [p.chunk_id for p in text_hits]]
        weights = [cfg.vector_weight, cfg.text_weight]
        pool = [*vector_hits, *text_hits]
        if hyde:
            hyde_vector = (await self._embedder.embed([hyde]))[0]
            hyde_hits = await self._store.vector_search(
                hyde_vector, name, search_filters, cfg.branch_limit
            )
            rankings.append([p.chunk_id for p in hyde_hits])
            weights.append(cfg.hyde_weight)
            pool.extend(hyde_hits)

        by_id = {p.chunk_id: p for p in pool}
        fused = reciprocal_rank_fusion(rankings, cfg.rrf_k, weights)
        ordered = [by_id[cid].with_score(score, "fusion") for cid, score in fused]
        if not cfg.prefilter and not filters.is_empty:
            ordered = [p for p in ordered if _passes(filters, p)]
        ordered = self._exclude(ordered, part.exclusions)
        candidates = _one_per_product(ordered)[: cfg.candidates]
        reranked = self._reranker.rerank(base_text, candidates, cfg.candidates, extras)
        return reranked, candidates

    def _exclude(self, passages: list[Passage], terms: tuple[str, ...]) -> list[Passage]:
        if not terms:
            return passages
        wanted = {stem(t) for t in terms}
        kept: list[Passage] = []
        for passage in passages:
            name_stems = {stem(t) for t in content_tokens(passage.name)}
            if name_stems & wanted or normalize(passage.category) in terms:
                continue
            kept.append(passage)
        return kept

    async def _diversify(self, passages: list[Passage]) -> list[Passage]:
        cfg = self._config
        if not cfg.mmr or len(passages) <= 1:
            return passages[: cfg.final]
        vectors = await self._store.embeddings([p.chunk_id for p in passages])
        order = mmr_select(
            {p.chunk_id: p.score for p in passages}, vectors, cfg.final, cfg.mmr_lambda
        )
        by_id = {p.chunk_id: p for p in passages}
        return [by_id[cid] for cid in order]

    async def _expand_parents(self, passages: list[Passage]) -> list[Passage]:
        if not self._config.parent_documents or not passages:
            return passages
        chunks = await self._store.product_chunks(
            self._embedder.name, [p.product_id for p in passages]
        )
        return [
            replace(p, content=merge_overlapping(chunks[p.product_id]))
            if p.product_id in chunks
            else p
            for p in passages
        ]


def _passes(filters: Filters, passage: Passage) -> bool:
    return filters.matches(
        passage.price_cents, passage.category, passage.rating, passage.product_id
    )


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
