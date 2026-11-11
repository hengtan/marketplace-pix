import logging
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from assistant.application.planner import last_products
from assistant.application.ports import Planner, Tool
from assistant.application.understanding import QueryUnderstanding
from assistant.domain.models import AgentOutcome, Observation, Passage, ToolCall, Turn
from assistant.telemetry import step_span

logger = logging.getLogger(__name__)


class AgentLoop:
    """plan -> act -> observe, at most `max_steps` times. The planner sees every observation so
    far and returns the next tool call or None when it has what it needs."""

    def __init__(
        self,
        planner: Planner,
        tools: Mapping[str, Tool],
        max_steps: int = 3,
        understanding: QueryUnderstanding | None = None,
    ) -> None:
        self._planner = planner
        self._tools = tools
        self._max_steps = max_steps
        self._understanding = understanding

    async def iterate(
        self, message: str, history: Sequence[Turn] = ()
    ) -> AsyncIterator[ToolCall | AgentOutcome]:
        outcome = AgentOutcome()
        if self._understanding is not None:
            with step_span("understand") as span:
                result = await self._understanding.classify(message, bool(last_products(history)))
                outcome.intent = result.intent.value
                span.set_attribute("assistant.intent", outcome.intent)
        for _ in range(self._max_steps):
            action = await self._planner.next_action(
                message, history, outcome.observations, outcome.intent
            )
            if action is None:
                break
            call, observation, passages = await self._execute(action.tool, action.arguments)
            outcome.tool_calls.append(call)
            outcome.observations.append(observation)
            if passages:
                outcome.passages = passages
            yield call
        yield outcome

    async def run(self, message: str, history: Sequence[Turn] = ()) -> AgentOutcome:
        outcome = AgentOutcome()
        async for item in self.iterate(message, history):
            if isinstance(item, AgentOutcome):
                outcome = item
        return outcome

    async def _execute(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[ToolCall, Observation, list[Passage]]:
        started = time.perf_counter()
        tool = self._tools.get(name)
        passages: list[Passage] = []
        if tool is None:
            summary, data, ok = f"Ferramenta desconhecida: {name}.", {}, False
        else:
            with step_span("tool", attributes={"assistant.tool": name}) as span:
                try:
                    result = await tool.run(dict(arguments))
                    summary, data, ok = result.summary, result.data, result.ok
                    passages = list(result.passages)
                except Exception as exc:
                    logger.warning("tool failed name=%s error=%s", name, type(exc).__name__)
                    summary, data, ok = f"Falha ao executar a ferramenta {name}.", {}, False
                span.set_attribute("assistant.tool.ok", ok)
        duration_ms = int((time.perf_counter() - started) * 1000)
        call = ToolCall(name, dict(arguments), summary, duration_ms, ok)
        return call, Observation(name, dict(arguments), summary, data, ok), passages
