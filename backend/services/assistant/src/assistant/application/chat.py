import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from assistant.application.agent import AgentLoop
from assistant.application.guardrails import GroundingGuard
from assistant.application.ports import LlmClient, SessionStore, StoredMessage
from assistant.application.prompt import PromptBuilder
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
    ) -> None:
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

        outcome = AgentOutcome()
        async for item in self._agent.iterate(message, history):
            if isinstance(item, AgentOutcome):
                outcome = item
            else:
                yield StreamEvent("tool_call", item)

        prompt = self._builder.build(message, outcome.passages, outcome.observations, history)
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
        await self._sessions.append(sid, "user", message, {})
        await self._sessions.append(
            sid,
            "assistant",
            verdict.answer,
            {
                "product_ids": [str(p) for p in remembered],
                "citations": [
                    {
                        "product_id": str(c.product_id),
                        "slug": c.slug,
                        "name": c.name,
                        "score": c.score,
                    }
                    for c in verdict.citations
                ],
                "tool_calls": [
                    {
                        "name": t.name,
                        "arguments": t.arguments,
                        "result_summary": t.result_summary,
                        "duration_ms": t.duration_ms,
                    }
                    for t in outcome.tool_calls
                ],
            },
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

    async def get_session(self, session_id: UUID) -> tuple[datetime, list[StoredMessage]]:
        created = await self._sessions.created_at(session_id)
        if created is None:
            raise SessionNotFound(str(session_id))
        return created, await self._sessions.messages(session_id)


def _remembered_products(citations: list[Citation], outcome: AgentOutcome) -> list[UUID]:
    ordered: list[UUID] = [c.product_id for c in citations]
    for obs in outcome.observations:
        raw = obs.data.get("product_id") if obs.tool == "get_stock" else None
        if raw and UUID(str(raw)) not in ordered:
            ordered.append(UUID(str(raw)))
    if not ordered:
        ordered = [p.product_id for p in outcome.passages]
    return ordered
