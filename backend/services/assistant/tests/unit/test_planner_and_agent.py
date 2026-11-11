from typing import Any
from uuid import uuid4

from assistant.application.agent import AgentLoop
from assistant.application.planner import RuleBasedPlanner
from assistant.application.ports import Action, ToolResult
from assistant.domain.errors import ToolError
from assistant.domain.models import AgentOutcome, Observation, Turn
from tests.helpers import passage, pid

planner = RuleBasedPlanner()


async def test_order_uuid_routes_to_order_status() -> None:
    order_id = uuid4()
    action = await planner.next_action(f"status do pedido {order_id}?", [], [])
    assert action == Action("get_order_status", {"order_id": str(order_id)})


async def test_order_tool_is_not_repeated() -> None:
    order_id = uuid4()
    seen = [Observation("get_order_status", {}, "ok", {})]
    assert await planner.next_action(f"pedido {order_id}", [], seen) is None


async def test_stock_question_searches_first_then_checks_stock_of_top_result() -> None:
    first = await planner.next_action("tem estoque do relógio GPS?", [], [])
    assert first is not None
    assert first.tool == "search_products"
    assert first.arguments["query"] == "relogio gps"

    found = Observation(
        "search_products",
        first.arguments,
        "1 produto",
        {"products": [{"product_id": str(pid("gps")), "name": "Relógio GPS Trail"}]},
    )
    second = await planner.next_action("tem estoque do relógio GPS?", [], [found])
    assert second == Action(
        "get_stock", {"product_id": str(pid("gps")), "name": "Relógio GPS Trail"}
    )

    done = Observation("get_stock", {}, "3 unidades", {})
    assert await planner.next_action("tem estoque do relógio GPS?", [], [found, done]) is None


async def test_stock_question_without_search_results_stops() -> None:
    empty = Observation("search_products", {}, "nada", {"products": []})
    assert await planner.next_action("tem estoque do foguete?", [], [empty]) is None


async def test_default_intent_is_product_search() -> None:
    action = await planner.next_action("quero um fone com cancelamento de ruído", [], [])
    assert action == Action("search_products", {"query": "quero um fone com cancelamento de ruído"})
    seen = [Observation("search_products", {}, "x", {})]
    assert await planner.next_action("quero um fone", [], seen) is None


async def test_order_question_without_code_uses_no_tool() -> None:
    assert await planner.next_action("onde está meu pedido?", [], []) is None


def _history(*ids: str) -> list[Turn]:
    return [
        Turn("user", "me mostre fones"),
        Turn("assistant", "Encontrei", product_ids=tuple(pid(i) for i in ids)),
    ]


async def test_memory_resolves_singular_reference_for_stock() -> None:
    action = await planner.next_action("e esse tem estoque?", _history("fone", "caixa"), [])
    assert action == Action("get_stock", {"product_id": str(pid("fone"))})


async def test_memory_restricts_search_for_plural_reference() -> None:
    action = await planner.next_action("qual o mais barato deles?", _history("fone", "caixa"), [])
    assert action is not None
    assert action.tool == "search_products"
    assert action.arguments["product_ids"] == [str(pid("fone")), str(pid("caixa"))]


async def test_reference_without_memory_falls_back_to_plain_search() -> None:
    action = await planner.next_action("qual o mais barato deles?", [], [])
    assert action is not None
    assert "product_ids" not in action.arguments


class ScriptedPlanner:
    def __init__(self, actions: list[Action | None]) -> None:
        self._actions = actions
        self.seen: list[int] = []

    async def next_action(
        self, message: str, history: Any, observations: list[Observation]
    ) -> Action | None:
        self.seen.append(len(observations))
        return self._actions.pop(0) if self._actions else Action("echo", {"n": len(observations)})


class EchoTool:
    name = "echo"

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(f"echo {arguments}", {"echo": arguments}, (passage("fone"),))


class BrokenTool:
    name = "broken"

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        raise ToolError("boom with secret data")


async def test_loop_never_runs_more_than_max_steps() -> None:
    scripted = ScriptedPlanner([])
    loop = AgentLoop(scripted, {"echo": EchoTool()}, max_steps=3)
    outcome = await loop.run("oi")
    assert len(outcome.tool_calls) == 3
    assert scripted.seen == [0, 1, 2]


async def test_loop_stops_when_planner_returns_none() -> None:
    loop = AgentLoop(ScriptedPlanner([Action("echo", {}), None]), {"echo": EchoTool()})
    outcome = await loop.run("oi")
    assert [t.name for t in outcome.tool_calls] == ["echo"]
    assert outcome.passages[0].slug == "fone"
    assert outcome.tool_calls[0].duration_ms >= 0


async def test_tool_error_becomes_an_observation_and_does_not_leak_details() -> None:
    loop = AgentLoop(ScriptedPlanner([Action("broken", {}), None]), {"broken": BrokenTool()})
    outcome = await loop.run("oi")
    call = outcome.tool_calls[0]
    assert call.ok is False
    assert "secret" not in call.result_summary
    assert outcome.observations[0].ok is False


async def test_unknown_tool_is_reported_not_raised() -> None:
    loop = AgentLoop(ScriptedPlanner([Action("rm_rf", {}), None]), {})
    outcome = await loop.run("oi")
    assert outcome.tool_calls[0].ok is False
    assert "desconhecida" in outcome.tool_calls[0].result_summary


async def test_iterate_yields_each_call_then_the_outcome() -> None:
    loop = AgentLoop(ScriptedPlanner([Action("echo", {}), None]), {"echo": EchoTool()})
    items = [item async for item in loop.iterate("oi")]
    assert len(items) == 2
    assert isinstance(items[-1], AgentOutcome)
