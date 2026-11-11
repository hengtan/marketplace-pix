import asyncio
import contextlib
import logging
import re
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from opentelemetry.trace import use_span

from assistant.application.agent import AgentLoop
from assistant.application.budget import BudgetManager
from assistant.application.fallback import DEGRADED_WARNING, SEARCH_UNAVAILABLE, build_fallback
from assistant.application.guardrails import (
    INJECTION_REFUSAL,
    GroundingGuard,
    screen_user_message,
)
from assistant.application.planner import last_products
from assistant.application.ports import LlmClient, Prompt, SessionStore, StoredMessage
from assistant.application.prompt import PromptBuilder
from assistant.application.semantic_cache import CacheHit, SemanticCache
from assistant.domain.cost import CostModel, estimate_tokens
from assistant.domain.errors import MessageTooLong, SessionNotFound
from assistant.domain.models import AgentOutcome, Citation, Observation, Passage, ToolCall, Turn
from assistant.metrics import (
    CHAT_REQUESTS,
    FALLBACKS,
    GUARDRAIL_EVENTS,
    LLM_COST,
    LLM_REQUESTS,
    LLM_TOKENS,
    STEP_DURATION,
    STREAMS_CANCELLED,
)
from assistant.telemetry import ChatTrace, is_done, next_in_span, preview, step_span

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
    degraded: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class StreamTimeouts:
    first_token: float = 15.0
    idle: float = 10.0
    total: float = 60.0


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
        budget: BudgetManager | None = None,
        timeouts: StreamTimeouts | None = None,
    ) -> None:
        self._timeouts = timeouts or StreamTimeouts()
        self._budget = budget
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

    async def chat(
        self, session_id: UUID | None, message: str, user_id: str | None = None
    ) -> ChatResult:
        result: ChatResult | None = None
        async for event in self.stream(session_id, message, stream_tokens=False, user_id=user_id):
            if event.kind == "done":
                result = event.payload
        assert result is not None
        return result

    async def stream(
        self,
        session_id: UUID | None,
        message: str,
        stream_tokens: bool = True,
        user_id: str | None = None,
    ) -> AsyncGenerator[StreamEvent]:
        started = time.perf_counter()
        message = self.validate_message(message)
        trace = ChatTrace()
        trace.set_attribute("assistant.question", preview(message))
        intent = "none"
        outcome_label = "error"
        failure: BaseException | None = None
        try:
            sid = session_id or uuid4()
            trace.set_attribute("assistant.session_id", str(sid))
            with trace.scope():
                await self._sessions.ensure(sid)
                history = [_to_turn(m) for m in await self._sessions.messages(sid, self._window)]

            if screen_user_message(message):
                GUARDRAIL_EVENTS.labels("injection_blocked").inc()
                with trace.scope():
                    await self._persist(sid, message, INJECTION_REFUSAL, [], [], [])
                latency_ms = int((time.perf_counter() - started) * 1000)
                outcome_label = "blocked"
                yield StreamEvent(
                    "done", ChatResult(sid, INJECTION_REFUSAL, [], [], [], latency_ms, True)
                )
                return

            if self._cache is not None:
                with trace.scope(), step_span("cache") as cache_span:
                    hit, cache_intent = await self._cache.lookup(
                        message, bool(last_products(history))
                    )
                    cache_span.set_attribute("assistant.cache.hit", hit is not None)
                if hit is not None:
                    intent = cache_intent
                    outcome_label = "cached"
                    async for event in self._replay(sid, message, hit, stream_tokens, started):
                        yield event
                    return

            outcome = AgentOutcome()
            iterator = self._agent.iterate(message, history).__aiter__()
            while True:
                item = await next_in_span(iterator, trace.span)
                if is_done(item):
                    break
                if isinstance(item, AgentOutcome):
                    outcome = item
                else:
                    yield StreamEvent("tool_call", item)
            intent = outcome.intent or "none"
            trace.set_attribute("assistant.intent", intent)

            prompt = self._builder.build(
                message, outcome.passages, outcome.observations, history, outcome.intent
            )
            prompt_tokens = estimate_tokens(prompt.text)
            if self._budget is not None:
                with trace.scope():
                    await self._budget.reserve(str(sid), user_id, prompt_tokens)

            if not outcome.passages and any(
                not o.ok and o.tool == "search_products" for o in outcome.observations
            ):
                FALLBACKS.labels("search_unavailable").inc()
                with trace.scope():
                    await self._persist(
                        sid, message, SEARCH_UNAVAILABLE, [], outcome.tool_calls, []
                    )
                outcome_label = "degraded"
                yield StreamEvent(
                    "done",
                    ChatResult(
                        sid,
                        SEARCH_UNAVAILABLE,
                        [],
                        outcome.tool_calls,
                        [],
                        int((time.perf_counter() - started) * 1000),
                        degraded=True,
                        warning=SEARCH_UNAVAILABLE,
                    ),
                )
                return

            generate = trace.child("generate")
            generate.handle.set_attribute("gen_ai.request.model", self._llm.name)
            generate.handle.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)
            parts: list[str] = []
            llm_stream: AsyncIterator[str] | None = None
            failure_reason: str | None = None
            deadline = time.monotonic() + self._timeouts.total
            try:
                if stream_tokens:
                    llm_stream = self._llm.stream(prompt).__aiter__()
                    first = True
                    while True:
                        remaining = deadline - time.monotonic()
                        limit = min(
                            self._timeouts.first_token if first else self._timeouts.idle, remaining
                        )
                        if limit <= 0:
                            raise TimeoutError("generation deadline exceeded")
                        token = await asyncio.wait_for(
                            next_in_span(llm_stream, generate.handle.span), limit
                        )
                        first = False
                        if is_done(token):
                            break
                        parts.append(token)
                        yield StreamEvent("token", token)
                        if self._delay:
                            await asyncio.sleep(self._delay)
                    raw_answer = "".join(parts)
                else:
                    with use_span(
                        generate.handle.span,
                        end_on_exit=False,
                        record_exception=False,
                        set_status_on_exception=False,
                    ):
                        raw_answer = await asyncio.wait_for(
                            self._llm.generate(prompt), self._timeouts.total
                        )
            except (asyncio.CancelledError, GeneratorExit):
                generate.end()
                await self._release(llm_stream, sid, user_id, prompt_tokens, "".join(parts))
                raise
            except Exception as exc:
                generate.end(exc)
                LLM_REQUESTS.labels(self._llm.name, "error").inc()
                failure_reason = "timeout" if isinstance(exc, TimeoutError) else "llm_error"
                logger.warning(
                    "generation failed reason=%s error=%s", failure_reason, type(exc).__name__
                )
                await self._release(llm_stream, sid, user_id, prompt_tokens, "".join(parts))
            else:
                await self._close(llm_stream)

            if failure_reason is not None:
                FALLBACKS.labels(failure_reason).inc()
                answer, fallback_citations = build_fallback(outcome)
                remembered = _remembered_products(fallback_citations, outcome)
                with trace.scope():
                    await self._persist(
                        sid, message, answer, fallback_citations, outcome.tool_calls, remembered
                    )
                latency_ms = int((time.perf_counter() - started) * 1000)
                outcome_label = "degraded"
                yield StreamEvent("warning", {"detail": DEGRADED_WARNING, "reason": failure_reason})
                yield StreamEvent(
                    "done",
                    ChatResult(
                        sid,
                        answer,
                        fallback_citations,
                        outcome.tool_calls,
                        [c.passage for c in prompt.context],
                        latency_ms,
                        grounded=True,
                        degraded=True,
                        warning=DEGRADED_WARNING,
                    ),
                )
                return

            completion_tokens = estimate_tokens(raw_answer)
            generate.handle.set_attribute("gen_ai.usage.output_tokens", completion_tokens)
            cost = self._cost.cost_usd(prompt_tokens, completion_tokens)
            generate.handle.set_attribute("assistant.cost_usd", round(cost, 8))
            generate.end()
            LLM_REQUESTS.labels(self._llm.name, "ok").inc()
            LLM_TOKENS.labels(self._llm.name, "prompt").inc(prompt_tokens)
            LLM_TOKENS.labels(self._llm.name, "completion").inc(completion_tokens)
            LLM_COST.labels(self._llm.name).inc(cost)

            allowed = [str(o.data["name"]) for o in outcome.observations if o.data.get("name")]
            known = await self._known_names()
            with trace.scope(), step_span("guard") as guard_span:
                verdict = self._guard.verify(
                    raw_answer,
                    [c.passage for c in prompt.context],
                    allowed,
                    known,
                    _evidence(outcome.observations),
                    message,
                )
                guard_span.set_attribute("assistant.guard.issues", len(verdict.issues))
            if verdict.issues:
                GUARDRAIL_EVENTS.labels("answer_corrected").inc()
            with trace.scope():
                if self._budget is not None:
                    await self._budget.record(
                        str(sid), user_id, prompt_tokens, estimate_tokens(verdict.answer)
                    )
                remembered = _remembered_products(verdict.citations, outcome)
                await self._persist(
                    sid, message, verdict.answer, verdict.citations, outcome.tool_calls, remembered
                )
                restricted = any("product_ids" in t.arguments for t in outcome.tool_calls)
                if (
                    self._cache is not None
                    and verdict.grounded
                    and outcome.intent
                    and not restricted
                ):
                    await self._cache.store(
                        message,
                        outcome.intent,
                        _cache_payload(
                            verdict.answer, verdict.citations, prompt, outcome.tool_calls
                        ),
                        [c.passage.product_id for c in prompt.context],
                        prompt_tokens + estimate_tokens(verdict.answer),
                        [t.name for t in outcome.tool_calls],
                    )
            latency_ms = int((time.perf_counter() - started) * 1000)
            outcome_label = "ok"
            trace.set_attribute("assistant.grounded", verdict.grounded)
            trace.set_attribute("assistant.latency_ms", latency_ms)
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
        except BaseException as exc:
            failure = exc
            raise
        finally:
            cancelled = isinstance(failure, GeneratorExit | asyncio.CancelledError)
            if cancelled:
                outcome_label = "cancelled"
                STREAMS_CANCELLED.inc()
            trace.set_attribute("assistant.outcome", outcome_label)
            trace.end(None if cancelled else failure)
            CHAT_REQUESTS.labels(intent, outcome_label).inc()
            STEP_DURATION.labels("total").observe(time.perf_counter() - started)

    @staticmethod
    async def _close(iterator: AsyncIterator[str] | None) -> None:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            with contextlib.suppress(Exception):
                await close()

    async def _release(
        self,
        iterator: AsyncIterator[str] | None,
        sid: UUID,
        user_id: str | None,
        prompt_tokens: int,
        partial: str,
    ) -> None:
        """Frees what a request that stopped early still holds: the model connection is closed
        so the provider stops generating, and the tokens already spent are booked."""
        await self._close(iterator)
        if self._budget is not None:
            with contextlib.suppress(Exception):
                await self._budget.record(
                    str(sid), user_id, prompt_tokens, estimate_tokens(partial)
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


def _evidence(observations: Sequence[Observation]) -> list[str]:
    evidence: list[str] = []
    for obs in observations:
        evidence.append(obs.summary)
        evidence.extend(str(v) for v in obs.data.values() if isinstance(v, str | int | float))
    return evidence


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
