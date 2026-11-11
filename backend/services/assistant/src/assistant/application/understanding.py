import time
from dataclasses import dataclass, field
from typing import Protocol

from assistant.application.ports import ChunkStore
from assistant.domain.filters import FilterParser
from assistant.domain.models import Filters
from assistant.domain.text import content_tokens
from assistant.domain.understanding import (
    Correction,
    IntentClassifier,
    IntentResult,
    QueryDecomposer,
    SynonymExpander,
    TypoCorrector,
    Vocabulary,
    extract_negations,
    hypothetical_document,
)

SNAPSHOT_TTL_SECONDS = 60.0


class HydeGenerator(Protocol):
    async def hypothesize(self, query: str, tokens: list[str], expansions: list[str]) -> str: ...


class TemplateHyde:
    async def hypothesize(self, query: str, tokens: list[str], expansions: list[str]) -> str:
        return hypothetical_document(tokens, expansions)


@dataclass(frozen=True)
class PlanOptions:
    typo_correction: bool = False
    expand: bool = False
    hyde: bool = False
    decompose: bool = False
    negation: bool = False


@dataclass(frozen=True)
class QueryPart:
    text: str
    filters: Filters
    sort: str | None
    tokens: list[str]
    corrections: list[Correction] = field(default_factory=list)
    expansions: list[str] = field(default_factory=list)
    hyde: str | None = None
    exclusions: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryPlan:
    original: str
    parts: list[QueryPart]

    @property
    def decomposed(self) -> bool:
        return len(self.parts) > 1


@dataclass
class _Snapshot:
    created: float
    categories: dict[str, str]
    parser: FilterParser
    classifier: IntentClassifier
    corrector: TypoCorrector
    decomposer: QueryDecomposer


class QueryUnderstanding:
    """Turns a raw question into an intent and a retrieval plan: filters, typo fixes, synonym
    expansion, a hypothetical document (HyDE), sub-questions and negated terms. Everything is
    derived from the indexed catalog, so it adapts when products change."""

    def __init__(
        self,
        store: ChunkStore,
        embedder_name: str,
        hyde: HydeGenerator | None = None,
        ttl_seconds: float = SNAPSHOT_TTL_SECONDS,
    ) -> None:
        self._store = store
        self._embedder = embedder_name
        self._hyde = hyde or TemplateHyde()
        self._ttl = ttl_seconds
        self._snapshot: _Snapshot | None = None
        self._expander = SynonymExpander()

    def invalidate(self) -> None:
        self._snapshot = None

    async def classify(self, question: str, has_remembered_products: bool = False) -> IntentResult:
        snap = await self._load()
        parsed = snap.parser.parse(question)
        return snap.classifier.classify(
            question, has_remembered_products, has_filters=not parsed.filters.is_empty
        )

    async def plan(self, question: str, options: PlanOptions | None = None) -> QueryPlan:
        options = options or PlanOptions()
        snap = await self._load()
        raw_parts = snap.decomposer.decompose(question) if options.decompose else [question]
        parts = [await self._plan_part(snap, text, options) for text in raw_parts]
        return QueryPlan(question, parts)

    async def _plan_part(self, snap: _Snapshot, text: str, options: PlanOptions) -> QueryPart:
        exclusions: tuple[str, ...] = ()
        positive = text
        if options.negation:
            negation = extract_negations(text)
            positive, exclusions = negation.text, negation.terms
        parsed = snap.parser.parse(positive)
        tokens = content_tokens(parsed.text)
        corrections: list[Correction] = []
        if options.typo_correction:
            tokens, corrections = snap.corrector.correct(tokens)
        expansions = self._expander.expand(tokens) if options.expand or options.hyde else []
        hyde = None
        if options.hyde and tokens:
            hyde = await self._hyde.hypothesize(text, tokens, expansions)
        return QueryPart(
            text,
            parsed.filters,
            parsed.sort,
            tokens,
            corrections,
            expansions if options.expand else [],
            hyde,
            exclusions,
        )

    async def _load(self) -> _Snapshot:
        snap = self._snapshot
        if snap is not None and time.monotonic() - snap.created < self._ttl:
            return snap
        categories = await self._store.categories(self._embedder)
        documents = await self._store.product_chunks(self._embedder)
        vocabulary = Vocabulary.from_documents(" ".join(c) for c in documents.values())
        snap = _Snapshot(
            time.monotonic(),
            categories,
            FilterParser(categories),
            IntentClassifier(vocabulary),
            TypoCorrector(vocabulary),
            QueryDecomposer(vocabulary),
        )
        self._snapshot = snap
        return snap
