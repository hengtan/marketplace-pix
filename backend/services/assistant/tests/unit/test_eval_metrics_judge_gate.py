import pytest

from assistant.application.gate import baseline_from, check_gate
from assistant.application.judge import JudgeInput, is_refusal
from assistant.domain.metrics import (
    context_precision,
    context_recall,
    hit_at_k,
    ndcg_at_k,
    reciprocal_rank,
)
from assistant.domain.numbers import extract_numbers
from assistant.infrastructure.judges.heuristic import HeuristicJudge


def test_hit_at_k_any_and_all() -> None:
    ranked = ["a", "b", "c", "d"]
    assert hit_at_k(ranked, {"c"}, 3) and not hit_at_k(ranked, {"d"}, 3)
    assert hit_at_k(ranked, {"a", "c"}, 3, require_all=True)
    assert not hit_at_k(ranked, {"a", "d"}, 3, require_all=True)
    assert not hit_at_k(ranked, set(), 3)


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["x", "y", "z"], {"z"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x"], {"q"}) == 0.0


def test_ndcg_rewards_better_ordering() -> None:
    gains = {"a": 1.0, "b": 1.0}
    assert ndcg_at_k(["a", "b", "x"], gains, 5) == pytest.approx(1.0)
    worse = ndcg_at_k(["x", "a", "b"], gains, 5)
    assert 0 < worse < 1
    assert ndcg_at_k(["x", "y"], gains, 5) == 0.0
    graded = ndcg_at_k(["b", "a"], {"a": 3.0, "b": 1.0}, 2)
    assert graded < 1.0


def test_context_precision_and_recall() -> None:
    assert context_precision(["a", "x", "b"], {"a", "b"}) == pytest.approx((1 + 2 / 3) / 2)
    assert context_precision(["x"], {"a"}) == 0.0
    assert context_recall(["a", "x"], {"a", "b"}, 4) == 0.5
    assert context_recall(["a", "b", "c"], {"a", "b", "c", "d", "e"}, 2) == 1.0
    assert context_recall([], set(), 4) == 0.0


def test_extract_numbers_handles_brazilian_formats() -> None:
    values = {float(n) for n in extract_numbers("R$ 1.299,90 em 3x, nota 4,7 de 5, 65W [2]")}
    assert values == {1299.9, 3.0, 4.7, 65.0}
    assert {float(n) for n in extract_numbers("nota 4.6")} == {4.6}


def _item(answer: str, answerable: bool = True, question: str = "fone bluetooth") -> JudgeInput:
    return JudgeInput(
        question,
        answer,
        ("Fone Nova R$ 349,90 nota 4.7 Cancelamento de ruído",),
        (),
        answerable,
        ("Fone Nova",),
    )


async def test_heuristic_judge_flags_a_wrong_price() -> None:
    judge = HeuristicJudge()
    good = await judge.judge(_item("O Fone Nova custa R$ 349,90, nota 4.7 de 5 [1]."))
    bad = await judge.judge(_item("O Fone Nova custa R$ 199,90 [1]."))
    assert good.faithfulness == 1.0 and bad.faithfulness == 0.0
    assert "199.9" in bad.reasons[0]


async def test_heuristic_judge_relevancy_for_answers_and_refusals() -> None:
    judge = HeuristicJudge()
    on_topic = await judge.judge(_item("Encontrei: Fone Nova, um fone bluetooth [1]."))
    assert on_topic.relevancy > 0.5
    refusal = "Não encontrei no catálogo nada que corresponda a isso."
    assert (await judge.judge(_item(refusal))).relevancy == 0.0
    assert (await judge.judge(_item(refusal, answerable=False))).relevancy == 1.0
    assert (await judge.judge(_item("O Fone Nova custa R$ 349,90.", False))).relevancy == 0.0
    assert is_refusal("Só consigo ajudar com produtos")


def test_gate_fails_below_floor_and_on_regression() -> None:
    metrics = {"hit_at_3": 0.95, "mrr": 0.85, "ndcg_at_5": 0.9}
    ok = check_gate(metrics, {"hit_at_3": 0.9}, {"hit_at_3": 0.96, "ndcg_at_5": 0.9})
    assert ok.passed
    floor = check_gate(metrics, {"mrr": 0.88})
    assert not floor.passed and "below minimum" in floor.failures[0]
    regression = check_gate(metrics, {}, {"hit_at_3": 0.99}, tolerance=0.02)
    assert not regression.passed and "regressed" in regression.failures[0]
    assert not check_gate({}, {"mrr": 0.5}).passed


def test_gate_ignores_latency_in_baseline_and_builds_baseline() -> None:
    metrics = {"hit_at_3": 0.9, "latency_p95_ms": 500}
    assert check_gate(metrics, {}, {"latency_p95_ms": 10.0}).passed
    assert baseline_from(metrics, ["hit_at_3"]) == {"hit_at_3": 0.9}
