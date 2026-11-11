import logging
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from assistant.application.ports import Planner, Tool
from assistant.domain.models import AgentOutcome, Observation, Passage, ToolCall, Turn

logger = logging.getLogger(__name__)


class AgentLoop:
    """plan -> act -> observe, at most `max_steps` times. The planner sees every observation so
    far and returns the next tool call or None when it has what it needs."""

    def __init__(self, planner: Planner, tools: Mapping[str, Tool], max_steps: int = 3) -> None:
        self._planner = planner
        self._tools = tools
        self._max_steps = max_steps

    async def iterate(
        self, message: str, history: Sequence[Turn] = ()
    ) -> AsyncIterator[ToolCall | AgentOutcome]:
        outcome = AgentOutcome()
        for _ in range(self._max_steps):
            action = await self._planner.next_action(message, history, outcome.observations)
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
            try:
                result = await tool.run(dict(arguments))
                summary, data, ok = result.summary, result.data, result.ok
                passages = list(result.passages)
            except Exception as exc:
                logger.warning("tool failed name=%s error=%s", name, type(exc).__name__)
                summary, data, ok = f"Falha ao executar a ferramenta {name}.", {}, False
        duration_ms = int((time.perf_counter() - started) * 1000)
        call = ToolCall(name, dict(arguments), summary, duration_ms, ok)
        return call, Observation(name, dict(arguments), summary, data, ok), passages
