import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from assistant.application.agent import AgentLoop
from assistant.application.guardrails import GroundingGuard
from assistant.application.planner import last_products
from assistant.application.ports import LlmClient, Prompt, SessionStore, StoredMessage
from assistant.application.prompt import PromptBuilder
from assistant.application.semantic_cache import CacheHit, SemanticCache
from assistant.domain.cost import CostModel, estimate_tokens
from assistant.domain.errors import MessageTooLong, SessionNotFound
from assistant.domain.models import AgentOutcome, Citation, Passage, ToolCall, Turn

logger = logging.getLogger(__name__)


@dataclass
class ChatResult:
    session_id: UUID
    answer: str
    citations: list[Citation]
    tool_calls: list[ToolCall]
    retrieved: list[Passage]
    latency_ms: int
    grounded: bool = True
    cached: bool = False


@dataclass(frozen=True)
class StreamEvent:
    kind: str
    payload: Any = field(default=None)


def _to_turn(message: StoredMessage) -> Turn:
    raw = message.meta.get("product_ids") or []
    return Turn(
        role=message.role,
        content=message.content,
        product_ids=tuple(UUID(str(p)) for p in raw),
        created_at=message.created_at,
        citations=tuple(message.meta.get("citations") or ()),
        tool_calls=tuple(message.meta.get("tool_calls") or ()),
    )


class ChatService:
    def __init__(
        self,
        agent: AgentLoop,
        builder: PromptBuilder,
        llm: LlmClient,
        sessions: SessionStore,
        guard: GroundingGuard,
        known_names: Callable[[], Awaitable[Sequence[str]]],
        max_message_chars: int = 1000,
        history_window: int = 6,
        token_delay_seconds: float = 0.0,
        cache: SemanticCache | None = None,
        cost: CostModel | None = None,
    ) -> None:
        self._cache = cache
        self._cost = cost or CostModel()
        self._agent = agent
        self._builder = builder
        self._llm = llm
        self._sessions = sessions
        self._guard = guard
        self._known_names = known_names
        self._max_chars = max_message_chars
        self._window = history_window
        self._delay = token_delay_seconds

    def validate_message(self, message: str) -> str:
        message = message.strip()
        if not message:
            raise ValueError("message must not be empty")
        if len(message) > self._max_chars:
            raise MessageTooLong(f"message exceeds {self._max_chars} characters")
        return message

    async def chat(self, session_id: UUID | None, message: str) -> ChatResult:
        result: ChatResult | None = None
        async for event in self.stream(session_id, message, stream_tokens=False):
            if event.kind == "done":
                result = event.payload
        assert result is not None
        return result

    async def stream(
        self, session_id: UUID | None, message: str, stream_tokens: bool = True
    ) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()
        message = self.validate_message(message)

        sid = session_id or uuid4()
        await self._sessions.ensure(sid)
        history = [_to_turn(m) for m in await self._sessions.messages(sid, self._window)]

        if self._cache is not None:
            hit, _ = await self._cache.lookup(message, bool(last_products(history)))
            if hit is not None:
                async for event in self._replay(sid, message, hit, stream_tokens, started):
                    yield event
                return

        outcome = AgentOutcome()
        async for item in self._agent.iterate(message, history):
            if isinstance(item, AgentOutcome):
                outcome = item
            else:
                yield StreamEvent("tool_call", item)

        prompt = self._builder.build(
            message, outcome.passages, outcome.observations, history, outcome.intent
        )
        parts: list[str] = []
        if stream_tokens:
            async for token in self._llm.stream(prompt):
                parts.append(token)
                yield StreamEvent("token", token)
                if self._delay:
                    await asyncio.sleep(self._delay)
            raw_answer = "".join(parts)
        else:
            raw_answer = await self._llm.generate(prompt)

        allowed = [str(o.data["name"]) for o in outcome.observations if o.data.get("name")]
        verdict = self._guard.verify(
            raw_answer,
            [c.passage for c in prompt.context],
            allowed,
            await self._known_names(),
        )

        remembered = _remembered_products(verdict.citations, outcome)
        await self._persist(
            sid, message, verdict.answer, verdict.citations, outcome.tool_calls, remembered
        )
        restricted = any("product_ids" in t.arguments for t in outcome.tool_calls)
        if self._cache is not None and verdict.grounded and outcome.intent and not restricted:
            await self._cache.store(
                message,
                outcome.intent,
                _cache_payload(verdict.answer, verdict.citations, prompt, outcome.tool_calls),
                [c.passage.product_id for c in prompt.context],
                estimate_tokens(prompt.text) + estimate_tokens(verdict.answer),
                [t.name for t in outcome.tool_calls],
            )
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "chat done session=%s tools=%d retrieved=%d cited=%d grounded=%s latency_ms=%d",
            sid,
            len(outcome.tool_calls),
            len(outcome.passages),
            len(verdict.citations),
            verdict.grounded,
            latency_ms,
        )
        yield StreamEvent(
            "done",
            ChatResult(
                session_id=sid,
                answer=verdict.answer,
                citations=verdict.citations,
                tool_calls=outcome.tool_calls,
                retrieved=[c.passage for c in prompt.context],
                latency_ms=latency_ms,
                grounded=verdict.grounded,
            ),
        )

    async def _persist(
        self,
        sid: UUID,
        message: str,
        answer: str,
        citations: list[Citation],
        tool_calls: list[ToolCall],
        remembered: list[UUID],
    ) -> None:
        await self._sessions.append(sid, "user", message, {})
        await self._sessions.append(
            sid,
            "assistant",
            answer,
            {
                "product_ids": [str(p) for p in remembered],
                "citations": [_citation_dict(c) for c in citations],
                "tool_calls": [_tool_call_dict(t) for t in tool_calls],
            },
        )

    async def _replay(
        self, sid: UUID, message: str, hit: CacheHit, stream_tokens: bool, started: float
    ) -> AsyncIterator[StreamEvent]:
        payload = hit.payload
        tool_calls = [
            ToolCall(t["name"], t["arguments"], t["result_summary"], 0)
            for t in payload["tool_calls"]
        ]
        for call in tool_calls:
            yield StreamEvent("tool_call", call)
        answer: str = payload["answer"]
        if stream_tokens:
            for token in re.findall(r"\S+\s*", answer):
                yield StreamEvent("token", token)
                if self._delay:
                    await asyncio.sleep(self._delay)
        citations = [
            Citation(UUID(c["product_id"]), c["slug"], c["name"], c["score"])
            for c in payload["citations"]
        ]
        retrieved = [_passage_from_dict(p) for p in payload["retrieved"]]
        remembered = [c.product_id for c in citations] or [p.product_id for p in retrieved]
        await self._persist(sid, message, answer, citations, tool_calls, remembered)
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info("chat cache hit session=%s latency_ms=%d", sid, latency_ms)
        yield StreamEvent(
            "done",
            ChatResult(sid, answer, citations, tool_calls, retrieved, latency_ms, True, True),
        )

    async def get_session(self, session_id: UUID) -> tuple[datetime, list[StoredMessage]]:
        created = await self._sessions.created_at(session_id)
        if created is None:
            raise SessionNotFound(str(session_id))
        return created, await self._sessions.messages(session_id)


def _citation_dict(c: Citation) -> dict[str, Any]:
    return {"product_id": str(c.product_id), "slug": c.slug, "name": c.name, "score": c.score}


def _tool_call_dict(t: ToolCall) -> dict[str, Any]:
    return {
        "name": t.name,
        "arguments": t.arguments,
        "result_summary": t.result_summary,
        "duration_ms": t.duration_ms,
    }


def _passage_dict(p: Passage) -> dict[str, Any]:
    return {
        "chunk_id": p.chunk_id,
        "product_id": str(p.product_id),
        "slug": p.slug,
        "name": p.name,
        "category": p.category,
        "price_cents": p.price_cents,
        "rating": p.rating,
        "content": p.content,
        "score": p.score,
        "source": p.source,
    }


def _passage_from_dict(raw: dict[str, Any]) -> Passage:
    return Passage(
        raw["chunk_id"],
        UUID(raw["product_id"]),
        raw["slug"],
        raw["name"],
        raw["category"],
        raw["price_cents"],
        raw["rating"],
        raw["content"],
        raw["score"],
        raw["source"],
    )


def _cache_payload(
    answer: str, citations: list[Citation], prompt: Prompt, tool_calls: list[ToolCall]
) -> dict[str, Any]:
    return {
        "answer": answer,
        "citations": [_citation_dict(c) for c in citations],
        "retrieved": [_passage_dict(i.passage) for i in prompt.context],
        "tool_calls": [_tool_call_dict(t) for t in tool_calls],
    }


def _remembered_products(citations: list[Citation], outcome: AgentOutcome) -> list[UUID]:
    ordered: list[UUID] = [c.product_id for c in citations]
    for obs in outcome.observations:
        raw = obs.data.get("product_id") if obs.tool == "get_stock" else None
        if raw and UUID(str(raw)) not in ordered:
            ordered.append(UUID(str(raw)))
    if not ordered:
        ordered = [p.product_id for p in outcome.passages]
    return ordered
