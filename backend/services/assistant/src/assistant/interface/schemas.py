from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from assistant.application.chat import ChatResult
from assistant.application.ports import EvalRunRecord, StoredMessage
from assistant.domain.models import Citation, Passage, ToolCall

Message = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class ChatRequest(BaseModel):
    session_id: UUID | None = None
    message: Message


class CitationOut(BaseModel):
    product_id: UUID
    slug: str
    name: str
    score: float

    @classmethod
    def from_domain(cls, c: Citation) -> CitationOut:
        return cls(product_id=c.product_id, slug=c.slug, name=c.name, score=c.score)


class ToolCallOut(BaseModel):
    name: str
    arguments: dict[str, Any]
    result_summary: str
    duration_ms: int

    @classmethod
    def from_domain(cls, t: ToolCall) -> ToolCallOut:
        return cls(
            name=t.name,
            arguments=t.arguments,
            result_summary=t.result_summary,
            duration_ms=t.duration_ms,
        )


class RetrievedOut(BaseModel):
    chunk_id: str
    product_id: UUID
    slug: str
    name: str
    category: str
    price_cents: int
    content: str
    score: float
    source: str

    @classmethod
    def from_domain(cls, p: Passage) -> RetrievedOut:
        return cls(
            chunk_id=p.chunk_id,
            product_id=p.product_id,
            slug=p.slug,
            name=p.name,
            category=p.category,
            price_cents=p.price_cents,
            content=p.content,
            score=p.score,
            source=p.source,
        )


class ChatResponse(BaseModel):
    session_id: UUID
    answer: str
    citations: list[CitationOut]
    tool_calls: list[ToolCallOut]
    retrieved: list[RetrievedOut]
    latency_ms: int
    cached: bool = False
    degraded: bool = False
    warning: str | None = None

    @classmethod
    def from_result(cls, r: ChatResult) -> ChatResponse:
        return cls(
            session_id=r.session_id,
            answer=r.answer,
            citations=[CitationOut.from_domain(c) for c in r.citations],
            tool_calls=[ToolCallOut.from_domain(t) for t in r.tool_calls],
            retrieved=[RetrievedOut.from_domain(p) for p in r.retrieved],
            latency_ms=r.latency_ms,
            cached=r.cached,
            degraded=r.degraded,
            warning=r.warning,
        )


class MessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime
    citations: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]

    @classmethod
    def from_stored(cls, m: StoredMessage) -> MessageOut:
        return cls(
            role=m.role,
            content=m.content,
            created_at=m.created_at,
            citations=m.meta.get("citations", []),
            tool_calls=m.meta.get("tool_calls", []),
        )


class SessionOut(BaseModel):
    session_id: UUID
    created_at: datetime
    messages: list[MessageOut]


class CacheStatsOut(BaseModel):
    enabled: bool
    entries: int
    persisted_hits: int
    persisted_tokens_saved: int
    lookups: int
    hits: int
    misses: int
    skips: int
    hit_rate: float
    tokens_saved: int
    cost_saved_usd: float


class ReindexOut(BaseModel):
    indexed: int
    skipped: int
    removed: int
    flagged: int = 0


class EvalRunOut(BaseModel):
    run_id: UUID
    created_at: datetime
    passed: bool
    embedder: str
    llm: str
    metrics: dict[str, Any]
    thresholds: dict[str, Any]
    cases: list[dict[str, Any]]

    @classmethod
    def from_record(cls, r: EvalRunRecord) -> EvalRunOut:
        return cls(
            run_id=r.run_id,
            created_at=r.created_at,
            passed=r.passed,
            embedder=r.embedder,
            llm=r.llm,
            metrics=r.metrics,
            thresholds=r.thresholds,
            cases=r.cases,
        )
