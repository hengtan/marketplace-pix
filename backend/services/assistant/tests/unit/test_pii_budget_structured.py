import json
import logging
from typing import Any

import pytest

from assistant.application.budget import (
    BudgetConfig,
    BudgetExceeded,
    BudgetManager,
    InMemoryUsageStore,
)
from assistant.application.llm_planner import LlmPlanner
from assistant.application.planner import RuleBasedPlanner
from assistant.application.ports import Prompt
from assistant.application.structured import (
    StructuredOutputError,
    extract_json,
    generate_structured,
)
from assistant.domain.cost import CostModel, estimate_tokens
from assistant.domain.pii import redact
from assistant.infrastructure.judges.llm import JudgeScores, LlmJudge
from assistant.infrastructure.logging_pii import install_pii_redaction


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("meu cpf é 529.982.247-25", "[CPF]"),
        ("cpf 52998224725", "[CPF]"),
        ("cnpj 11.222.333/0001-81", "[CNPJ]"),
        ("escreva para maria.souza@empresa.com.br", "[EMAIL]"),
        ("ligue para (11) 91234-5678", "[TELEFONE]"),
        ("whatsapp +55 11 91234 5678", "[TELEFONE]"),
        ("cartão 4111 1111 1111 1111", "[CARTAO]"),
        ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456", "[TOKEN]"),
        ("chave sk-live_abcdefghijklmnop1234", "[TOKEN]"),
    ],
)
def test_pii_is_redacted(raw: str, label: str) -> None:
    out = redact(raw)
    assert label in out
    for secret in (
        "529.982",
        "52998224725",
        "11.222.333",
        "maria.souza",
        "91234",
        "4111 1111",
        "abcdefghij",
    ):
        assert secret not in out


@pytest.mark.parametrize(
    "text",
    [
        "pedido 3f2a9c1e-7b44-4d0e-9a51-0c2d5e8f1b66 pago",
        "cpf inválido 111.111.111-11",
        "cartão 1234 5678 9012 3456",
        "preço R$ 349,90 e nota 4,7",
        "produto 65W com 40 horas",
    ],
)
def test_non_personal_text_is_left_alone(text: str) -> None:
    assert redact(text) == text


def test_log_records_are_redacted(caplog: pytest.LogCaptureFixture) -> None:
    install_pii_redaction()
    install_pii_redaction()
    logger = logging.getLogger("assistant.test_pii")
    with caplog.at_level(logging.INFO, logger="assistant.test_pii"):
        logger.info("pergunta de %s cpf %s", "ana@loja.com", "529.982.247-25")
    text = caplog.text
    assert "[EMAIL]" in text and "[CPF]" in text
    assert "ana@loja.com" not in text and "529.982" not in text


async def test_session_budget_stops_a_flood() -> None:
    manager = BudgetManager(InMemoryUsageStore(), BudgetConfig(session_tokens=1000))
    for _ in range(4):
        await manager.reserve("s1", None, 200)
        await manager.record("s1", None, 200, 50)
    with pytest.raises(BudgetExceeded) as info:
        await manager.reserve("s1", None, 200)
    assert info.value.scope == "session" and info.value.limit == "tokens"
    await manager.reserve("s2", None, 200)


async def test_user_budget_spans_sessions_and_the_cost_cap_is_enforced() -> None:
    config = BudgetConfig(session_tokens=10_000, user_daily_tokens=500, user_daily_cost_usd=1.0)
    manager = BudgetManager(InMemoryUsageStore(), config)
    await manager.record("a", "user:1", 200, 100)
    await manager.record("b", "user:1", 100, 50)
    with pytest.raises(BudgetExceeded) as info:
        await manager.reserve("c", "user:1", 100)
    assert info.value.scope == "user"
    await manager.reserve("c", "user:2", 100)
    assert (await manager.remaining("a", "user:1"))["user_tokens"] == 50

    expensive = BudgetManager(
        InMemoryUsageStore(),
        BudgetConfig(session_tokens=10**9, session_cost_usd=0.001),
        CostModel(prompt_per_1k_usd=1.0, completion_per_1k_usd=1.0),
    )
    with pytest.raises(BudgetExceeded) as cost:
        await expensive.reserve("s", None, 5000)
    assert cost.value.limit == "cost"


async def test_disabled_budget_never_blocks() -> None:
    manager = BudgetManager(InMemoryUsageStore(), BudgetConfig(enabled=False, session_tokens=1))
    await manager.reserve("s", "u", 10**6)
    assert await manager.record("s", "u", 1000, 1000) > 0


def test_token_estimate_is_proportional_to_length() -> None:
    assert estimate_tokens("") == 0 and estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


class ScriptedLlm:
    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[Prompt] = []

    async def generate(self, prompt: Prompt) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)

    def stream(self, prompt: Prompt) -> Any:
        raise NotImplementedError


def _prompt() -> Prompt:
    return Prompt("sys", "q", (), (), "texto base")


def test_extract_json_handles_fences_text_and_nested_braces() -> None:
    assert json.loads(extract_json('```json\n{"a": {"b": "}"}}\n```')) == {"a": {"b": "}"}}
    assert json.loads(extract_json('Claro! {"x": 1} espero ter ajudado')) == {"x": 1}
    with pytest.raises(ValueError):
        extract_json("sem json")
    with pytest.raises(ValueError):
        extract_json('{"aberto": 1')


async def test_structured_output_is_repaired_with_the_validation_error() -> None:
    llm = ScriptedLlm(
        [
            "não sei",
            '{"faithfulness": 3, "relevancy": 0.5}',
            '{"faithfulness": 0.9, "relevancy": 0.5}',
        ]
    )
    scores = await generate_structured(llm, _prompt(), JudgeScores)  # type: ignore[arg-type]
    assert scores.faithfulness == 0.9 and len(llm.prompts) == 3
    assert "Sua resposta anterior não é válida" in llm.prompts[1].text
    assert "less than or equal to 1" in llm.prompts[2].text


async def test_structured_output_gives_up_after_the_retries() -> None:
    llm = ScriptedLlm(["x", "y", "z"])
    with pytest.raises(StructuredOutputError):
        await generate_structured(llm, _prompt(), JudgeScores, max_retries=2)  # type: ignore[arg-type]
    assert len(llm.prompts) == 3


async def test_llm_judge_returns_a_validated_verdict() -> None:
    from assistant.application.judge import JudgeInput

    llm = ScriptedLlm(['{"faithfulness": 1, "relevancy": 0.8, "reasons": ["ok"]}'])
    verdict = await LlmJudge(llm).judge(JudgeInput("q", "a", ("ctx",), (), True))  # type: ignore[arg-type]
    assert (verdict.faithfulness, verdict.relevancy, verdict.reasons) == (1.0, 0.8, ("ok",))


async def test_llm_planner_validates_the_tool_and_falls_back() -> None:
    tools = {"search_products": "busca", "get_stock": "estoque"}
    good = ScriptedLlm(['{"tool": "search_products", "arguments": {"query": "fone"}}'])
    action = await LlmPlanner(good, RuleBasedPlanner(), tools).next_action("fone", [], [])  # type: ignore[arg-type]
    assert action is not None and action.tool == "search_products"

    done = ScriptedLlm(['{"tool": null}'])
    assert await LlmPlanner(done, RuleBasedPlanner(), tools).next_action("fone", [], []) is None  # type: ignore[arg-type]

    hostile = ScriptedLlm(['{"tool": "delete_everything", "arguments": {}}'])
    fallback = await LlmPlanner(hostile, RuleBasedPlanner(), tools).next_action(
        "quero um fone", [], []
    )  # type: ignore[arg-type]
    assert fallback is not None and fallback.tool == "search_products"

    broken = ScriptedLlm(["nada", "nada"])
    again = await LlmPlanner(broken, RuleBasedPlanner(), tools).next_action("quero um fone", [], [])  # type: ignore[arg-type]
    assert again is not None and again.tool == "search_products"

    untouched = ScriptedLlm([])
    routed = await LlmPlanner(untouched, RuleBasedPlanner(), tools).next_action(
        "qual a capital?", [], [], "out_of_scope"
    )  # type: ignore[arg-type]
    assert routed is None and untouched.prompts == []
