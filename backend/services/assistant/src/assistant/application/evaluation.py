import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from assistant.application.chat import ChatResult, ChatService
from assistant.application.judge import JudgeInput, JudgeLlm
from assistant.application.ports import EvalRunRecord
from assistant.domain.metrics import (
    context_precision,
    context_recall,
    hit_at_k,
    ndcg_at_k,
    reciprocal_rank,
)
from assistant.domain.text import format_brl, normalize

TOP_K = 3
CONTEXT_CAP = 4


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    expected_products: tuple[str, ...] = ()
    expected_tool: str | None = None
    must_include: tuple[str, ...] = ()
    must_not_include: tuple[str, ...] = ()
    history: tuple[str, ...] = ()
    notes: str = ""
    category: str = "direct"
    split: str = "dev"
    forbidden_products: tuple[str, ...] = ()
    require_all: bool = False

    @property
    def answerable(self) -> bool:
        return bool(self.expected_products) or self.expected_tool in {
            "get_stock",
            "get_order_status",
            "get_policy",
        }


@dataclass
class CaseOutcome:
    case: EvalCase
    result: ChatResult
    retrieved_slugs: list[str] = field(default_factory=list)
    hit: bool | None = None
    recall: float | None = None
    reciprocal_rank: float | None = None
    hit_at_1: bool | None = None
    hit_at_5: bool | None = None
    ndcg: float | None = None
    ctx_precision: float | None = None
    ctx_recall: float | None = None
    negation_ok: bool | None = None
    faithfulness: float | None = None
    relevancy: float | None = None
    grounded: bool = True
    tool_ok: bool | None = None
    answer_ok: bool = True
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case.id,
            "question": self.case.question,
            "expected_products": list(self.case.expected_products),
            "retrieved": self.retrieved_slugs,
            "tools": [t.name for t in self.result.tool_calls],
            "answer": self.result.answer,
            "hit_at_3": self.hit,
            "recall_at_3": self.recall,
            "reciprocal_rank": self.reciprocal_rank,
            "ndcg_at_5": self.ndcg,
            "context_precision": self.ctx_precision,
            "context_recall": self.ctx_recall,
            "negation_ok": self.negation_ok,
            "faithfulness": self.faithfulness,
            "answer_relevancy": self.relevancy,
            "category": self.case.category,
            "split": self.case.split,
            "grounded": self.grounded,
            "tool_ok": self.tool_ok,
            "answer_ok": self.answer_ok,
            "latency_ms": self.result.latency_ms,
            "failures": self.failures,
        }


def load_cases(path: Path) -> list[EvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        EvalCase(
            id=item["id"],
            question=item["question"],
            expected_products=tuple(item.get("expected_products") or ()),
            expected_tool=item.get("expected_tool"),
            must_include=tuple(item.get("must_include") or ()),
            must_not_include=tuple(item.get("must_not_include") or ()),
            history=tuple(item.get("history") or ()),
            notes=item.get("notes", ""),
            category=item.get("category", "direct"),
            split=item.get("split", "dev"),
            forbidden_products=tuple(item.get("forbidden_products") or ()),
            require_all=bool(item.get("require_all", False)),
        )
        for item in raw
    ]


def percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    rank = max(math.ceil(pct / 100 * len(ordered)), 1)
    return ordered[rank - 1]


def score_case(case: EvalCase, result: ChatResult) -> CaseOutcome:
    outcome = CaseOutcome(case, result, [p.slug for p in result.retrieved])

    ranked = outcome.retrieved_slugs
    if case.expected_products:
        expected = set(case.expected_products)
        outcome.hit = hit_at_k(ranked, expected, TOP_K, case.require_all)
        outcome.hit_at_1 = hit_at_k(ranked, expected, 1, case.require_all)
        outcome.hit_at_5 = hit_at_k(ranked, expected, 5, case.require_all)
        outcome.recall = context_recall(ranked[:TOP_K], expected, TOP_K)
        outcome.reciprocal_rank = reciprocal_rank(ranked, expected)
        outcome.ndcg = ndcg_at_k(ranked, dict.fromkeys(expected, 1.0), 5)
        outcome.ctx_precision = context_precision(ranked, expected)
        outcome.ctx_recall = context_recall(ranked, expected, CONTEXT_CAP)
        if not outcome.hit:
            outcome.failures.append(f"expected {sorted(expected)} in top {TOP_K}")
    if case.forbidden_products:
        outcome.negation_ok = not set(case.forbidden_products) & set(ranked)
        if not outcome.negation_ok:
            outcome.failures.append(f"forbidden product retrieved: {case.forbidden_products}")

    retrieved_ids = {p.product_id for p in result.retrieved}
    cited_ok = all(c.product_id in retrieved_ids for c in result.citations)
    outcome.grounded = result.grounded and cited_ok
    if not outcome.grounded:
        outcome.failures.append("answer is not grounded in retrieved passages")

    if case.expected_tool is not None:
        used = [t.name for t in result.tool_calls]
        outcome.tool_ok = not used if case.expected_tool == "none" else case.expected_tool in used
        if not outcome.tool_ok:
            outcome.failures.append(f"expected tool {case.expected_tool}, used {used}")

    answer = normalize(result.answer)
    missing = [s for s in case.must_include if normalize(s) not in answer]
    forbidden = [s for s in case.must_not_include if normalize(s) in answer]
    outcome.answer_ok = not missing and not forbidden
    if missing:
        outcome.failures.append(f"answer lacks {missing}")
    if forbidden:
        outcome.failures.append(f"answer contains forbidden {forbidden}")
    return outcome


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _summary(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    def values(attr: str) -> list[float]:
        return [float(v) for o in outcomes if (v := getattr(o, attr)) is not None]

    latencies = [o.result.latency_ms for o in outcomes]
    tools = [1.0 if o.tool_ok else 0.0 for o in outcomes if o.tool_ok is not None]
    return {
        "hit_at_1": _mean(values("hit_at_1")),
        "hit_at_3": _mean(values("hit")),
        "hit_at_5": _mean(values("hit_at_5")),
        "recall_at_3": _mean(values("recall")),
        "mrr": _mean(values("reciprocal_rank")),
        "ndcg_at_5": _mean(values("ndcg")),
        "context_precision": _mean(values("ctx_precision")),
        "context_recall": _mean(values("ctx_recall")),
        "negation_pass": _mean(values("negation_ok")),
        "faithfulness": _mean(values("faithfulness")),
        "answer_relevancy": _mean(values("relevancy")),
        "groundedness": _mean([1.0 if o.grounded else 0.0 for o in outcomes]),
        "tool_accuracy": _mean(tools),
        "answer_pass": _mean([1.0 if o.answer_ok else 0.0 for o in outcomes]),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "cases": len(outcomes),
        "retrieval_cases": len(values("hit")),
        "tool_cases": len(tools),
    }


def aggregate(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    metrics = _summary(outcomes)
    for field_name, key in (("category", "by_category"), ("split", "by_split")):
        groups: dict[str, list[CaseOutcome]] = defaultdict(list)
        for outcome in outcomes:
            groups[getattr(outcome.case, field_name)].append(outcome)
        metrics[key] = {
            name: {
                k: v
                for k, v in _summary(group).items()
                if k in {"cases", "hit_at_3", "mrr", "ndcg_at_5", "answer_pass", "tool_accuracy"}
            }
            for name, group in sorted(groups.items())
        }
    return metrics


def check_thresholds(metrics: dict[str, Any], thresholds: dict[str, float]) -> dict[str, bool]:
    return {name: metrics[name] >= minimum for name, minimum in thresholds.items()}


class EvalRunner:
    def __init__(
        self,
        chat: ChatService,
        thresholds: dict[str, float],
        embedder: str,
        llm: str,
        judge: JudgeLlm | None = None,
    ) -> None:
        self._judge = judge
        self._chat = chat
        self._thresholds = thresholds
        self._embedder = embedder
        self._llm = llm

    async def run(self, cases: list[EvalCase]) -> EvalRunRecord:
        outcomes: list[CaseOutcome] = []
        for case in cases:
            session_id = uuid4()
            for earlier in case.history:
                await self._chat.chat(session_id, earlier)
            result = await self._chat.chat(session_id, case.question)
            outcome = score_case(case, result)
            if self._judge is not None:
                await self._apply_judge(outcome)
            outcomes.append(outcome)
        metrics = aggregate(outcomes)
        verdicts = check_thresholds(metrics, self._thresholds)
        return EvalRunRecord(
            run_id=uuid4(),
            created_at=datetime.now(UTC),
            passed=all(verdicts.values()),
            metrics=metrics,
            thresholds=dict(self._thresholds),
            cases=[o.to_dict() for o in outcomes],
            embedder=self._embedder,
            llm=self._llm,
        )

    async def _apply_judge(self, outcome: CaseOutcome) -> None:
        assert self._judge is not None
        verdict = await self._judge.judge(judge_input(outcome))
        outcome.faithfulness = verdict.faithfulness
        outcome.relevancy = verdict.relevancy
        if verdict.faithfulness < 1.0:
            outcome.failures.append(f"unfaithful: {'; '.join(verdict.reasons)}")


def judge_input(outcome: CaseOutcome) -> JudgeInput:
    contexts = tuple(
        f"{p.name} {format_brl(p.price_cents)} nota {p.rating:.1f} {p.content}"
        for p in outcome.result.retrieved
    )
    evidence = tuple(t.result_summary for t in outcome.result.tool_calls)
    return JudgeInput(
        outcome.case.question,
        outcome.result.answer,
        contexts,
        evidence,
        outcome.case.answerable,
        tuple(p.name for p in outcome.result.retrieved),
    )


def format_report(record: EvalRunRecord) -> str:
    rows = [("metric", "value", "minimum", "status")]
    for name, minimum in record.thresholds.items():
        value = record.metrics[name]
        rows.append((name, f"{value:.3f}", f"{minimum:.2f}", "ok" if value >= minimum else "FAIL"))
    extras = (
        "hit_at_1", "hit_at_5", "recall_at_3", "ndcg_at_5", "context_precision",
        "context_recall", "negation_pass", "faithfulness", "answer_relevancy",
        "latency_p50_ms", "latency_p95_ms",
    )  # fmt: skip
    for name in extras:
        if name in record.metrics and name not in record.thresholds:
            rows.append((name, f"{record.metrics[name]}", "-", "-"))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    header = (
        f"eval run {record.run_id} embedder={record.embedder} llm={record.llm} "
        f"cases={record.metrics['cases']}"
    )
    failing = [c for c in record.cases if c["failures"]]
    body = [header, "", *lines, ""]
    if failing:
        body.append("failing cases:")
        for case in failing:
            body.append(f"  {case['id']}: {'; '.join(case['failures'])}")
        body.append("")
    body.append("RESULT: " + ("PASS" if record.passed else "FAIL"))
    return "\n".join(body)
