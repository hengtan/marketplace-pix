import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from assistant.application.ports import Embedder
from assistant.application.understanding import PlanOptions, QueryUnderstanding
from assistant.domain.cost import CostModel
from assistant.domain.text import normalize, tokenize
from assistant.domain.understanding import REFERENCES
from assistant.metrics import (
    CACHE_COST_SAVED,
    CACHE_ENTRIES,
    CACHE_INVALIDATIONS,
    CACHE_REQUESTS,
    CACHE_TOKENS_SAVED,
)

logger = logging.getLogger(__name__)

NEGATION_WORDS = frozenset({"nao", "sem", "exceto", "menos", "tirando", "nenhum", "nunca"})
CACHEABLE_INTENTS = frozenset({"catalog", "policy"})
CACHEABLE_TOOLS = frozenset({"search_products", "get_policy"})


@dataclass(frozen=True)
class CacheConfig:
    enabled: bool = True
    threshold: float = 0.92
    ttl_seconds: int = 3600


@dataclass(frozen=True)
class CacheEntry:
    embedder: str
    filter_key: str
    intent: str
    query_text: str
    embedding: list[float]
    payload: dict[str, Any]
    product_ids: tuple[UUID, ...]
    volatile: bool
    tokens_saved: int
    ttl_seconds: int


@dataclass(frozen=True)
class CacheHit:
    payload: dict[str, Any]
    similarity: float
    tokens_saved: int
    query_text: str


@dataclass(frozen=True)
class CacheSummary:
    entries: int
    hits: int
    tokens_saved: int


class CacheStore(Protocol):
    async def lookup(
        self, embedding: list[float], embedder: str, filter_key: str, threshold: float
    ) -> CacheHit | None: ...

    async def put(self, entry: CacheEntry) -> None: ...

    async def invalidate_products(self, product_ids: list[UUID], include_volatile: bool) -> int: ...

    async def invalidate_all(self) -> int: ...

    async def purge_expired(self) -> int: ...

    async def summary(self) -> CacheSummary: ...


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    skips: int = 0
    tokens_saved: int = 0
    cost_saved_usd: float = 0.0
    extra: dict[str, int] = field(default_factory=dict)

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return round(self.hits / self.lookups, 4) if self.lookups else 0.0


class SemanticCache:
    """Answers repeated or paraphrased questions without running the agent and the model.
    A hit needs the same filters and negations (the key) and a cosine similarity above the
    threshold. Entries expire by TTL and are removed when a catalog event touches a product
    they cite."""

    def __init__(
        self,
        store: CacheStore,
        embedder: Embedder,
        understanding: QueryUnderstanding,
        config: CacheConfig | None = None,
        cost: CostModel | None = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._understanding = understanding
        self._config = config or CacheConfig()
        self._cost = cost or CostModel()
        self.stats = CacheStats()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    async def lookup(self, question: str, remembered: bool) -> tuple[CacheHit | None, str]:
        if not self._config.enabled or (remembered and _depends_on_history(question)):
            self.stats.skips += 1
            CACHE_REQUESTS.labels("skip").inc()
            return None, "skip"
        intent = (await self._understanding.classify(question, remembered)).intent.value
        if intent not in CACHEABLE_INTENTS:
            self.stats.skips += 1
            CACHE_REQUESTS.labels("skip").inc()
            return None, "skip"
        key = await self._filter_key(question)
        vector = (await self._embedder.embed([normalize(question)]))[0]
        hit = await self._store.lookup(vector, self._embedder.name, key, self._config.threshold)
        if hit is None:
            self.stats.misses += 1
            CACHE_REQUESTS.labels("miss").inc()
            return None, intent
        self.stats.hits += 1
        self.stats.tokens_saved += hit.tokens_saved
        saved = self._cost.cost_usd(hit.tokens_saved, 0)
        self.stats.cost_saved_usd += saved
        CACHE_REQUESTS.labels("hit").inc()
        CACHE_TOKENS_SAVED.inc(hit.tokens_saved)
        CACHE_COST_SAVED.inc(saved)
        logger.info("semantic cache hit similarity=%.3f", hit.similarity)
        return hit, intent

    async def store(
        self,
        question: str,
        intent: str,
        payload: dict[str, Any],
        product_ids: list[UUID],
        tokens: int,
        tool_names: list[str],
    ) -> bool:
        if (
            not self._config.enabled
            or intent not in CACHEABLE_INTENTS
            or not set(tool_names) <= CACHEABLE_TOOLS
            or _depends_on_history(question)
        ):
            return False
        key = await self._filter_key(question)
        vector = (await self._embedder.embed([normalize(question)]))[0]
        plan = await self._understanding.plan(question)
        part = plan.parts[0]
        volatile = not part.filters.is_empty or part.sort is not None or not product_ids
        await self._store.put(
            CacheEntry(
                self._embedder.name,
                key,
                intent,
                question,
                vector,
                payload,
                tuple(product_ids),
                volatile,
                tokens,
                self._config.ttl_seconds,
            )
        )
        return True

    async def invalidate_products(self, product_ids: list[UUID], include_volatile: bool) -> int:
        removed = await self._store.invalidate_products(product_ids, include_volatile)
        CACHE_INVALIDATIONS.labels("catalog_event").inc(removed)
        return removed

    async def invalidate_all(self) -> int:
        removed = await self._store.invalidate_all()
        CACHE_INVALIDATIONS.labels("flush").inc(removed)
        return removed

    async def purge_expired(self) -> int:
        removed = await self._store.purge_expired()
        CACHE_INVALIDATIONS.labels("ttl").inc(removed)
        return removed

    async def summary(self) -> CacheSummary:
        summary = await self._store.summary()
        CACHE_ENTRIES.set(summary.entries)
        return summary

    async def _filter_key(self, question: str) -> str:
        plan = await self._understanding.plan(question, PlanOptions(negation=True))
        part = plan.parts[0]
        negations = sorted(set(tokenize(question)) & NEGATION_WORDS)
        raw = json.dumps(
            [part.filters.to_dict(), part.sort, list(part.exclusions), negations], sort_keys=True
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _depends_on_history(question: str) -> bool:
    return bool(set(tokenize(question)) & REFERENCES)
