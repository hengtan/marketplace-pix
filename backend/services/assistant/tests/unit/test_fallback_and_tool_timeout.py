import asyncio
from typing import Any

from assistant.application.agent import AgentLoop
from assistant.application.fallback import UNAVAILABLE, build_fallback
from assistant.application.ports import Action, ToolResult
from assistant.domain.models import AgentOutcome, Observation
from tests.helpers import passage


def test_fallback_lists_search_results_with_catalog_prices_and_citations() -> None:
    outcome = AgentOutcome(
        passages=[passage("a", "Fone Nova", 34990, 4.7), passage("b", "Caixa Pulse", 21990, 4.5)]
    )
    answer, citations = build_fallback(outcome)
    assert "- Fone Nova por R$ 349,90, nota 4.7 de 5 [1]" in answer
    assert "- Caixa Pulse por R$ 219,90, nota 4.5 de 5 [2]" in answer
    assert [c.slug for c in citations] == ["a", "b"]


def test_fallback_uses_tool_facts_when_there_are_no_passages() -> None:
    outcome = AgentOutcome(
        observations=[
            Observation("get_stock", {}, "Fone Nova: 3 unidades disponíveis.", {}),
            Observation("get_order_status", {}, "falhou", {}, ok=False),
        ]
    )
    answer, citations = build_fallback(outcome)
    assert "3 unidades" in answer and "falhou" not in answer and citations == []


def test_fallback_without_anything_says_so() -> None:
    assert build_fallback(AgentOutcome()) == (UNAVAILABLE, [])


class SlowTool:
    name = "slow"

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        await asyncio.sleep(5)
        return ToolResult("nunca", {})


class OneShot:
    def __init__(self) -> None:
        self.calls = 0

    async def next_action(self, message: str, history: Any, observations: Any, intent: Any = None):  # type: ignore[no-untyped-def]
        self.calls += 1
        return Action("slow", {}) if self.calls == 1 else None


async def test_a_slow_tool_becomes_a_failed_observation_instead_of_hanging() -> None:
    loop = AgentLoop(OneShot(), {"slow": SlowTool()}, tool_timeout_seconds=0.05)
    outcome = await asyncio.wait_for(loop.run("oi"), 2)
    assert not outcome.tool_calls[0].ok
    assert "demorou demais" in outcome.tool_calls[0].result_summary
