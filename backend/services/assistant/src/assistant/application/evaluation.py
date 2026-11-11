import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from assistant.application.chat import ChatResult, ChatService
from assistant.application.ports import EvalRunRecord
from assistant.domain.text import normalize

TOP_K = 3


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


@dataclass
class CaseOutcome:
    case: EvalCase
    result: ChatResult
    retrieved_slugs: list[str] = field(default_factory=list)
    hit: bool | None = None
    recall: float | None = None
    reciprocal_rank: float | None = None
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

    if case.expected_products:
        expected = set(case.expected_products)
        top = outcome.retrieved_slugs[:TOP_K]
        found = expected & set(top)
        outcome.hit = bool(found)
        outcome.recall = len(found) / min(len(expected), TOP_K)
        outcome.reciprocal_rank = next(
            (1 / rank for rank, slug in enumerate(outcome.retrieved_slugs, 1) if slug in expected),
            0.0,
        )
        if not outcome.hit:
            outcome.failures.append(f"expected {sorted(expected)} in top {TOP_K}")

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


def aggregate(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    hits = [1.0 if o.hit else 0.0 for o in outcomes if o.hit is not None]
    recalls = [o.recall for o in outcomes if o.recall is not None]
    ranks = [o.reciprocal_rank for o in outcomes if o.reciprocal_rank is not None]
    tools = [1.0 if o.tool_ok else 0.0 for o in outcomes if o.tool_ok is not None]
    latencies = [o.result.latency_ms for o in outcomes]
    return {
        "hit_at_3": _mean(hits),
        "recall_at_3": _mean(recalls),
        "mrr": _mean(ranks),
        "groundedness": _mean([1.0 if o.grounded else 0.0 for o in outcomes]),
        "tool_accuracy": _mean(tools),
        "answer_pass": _mean([1.0 if o.answer_ok else 0.0 for o in outcomes]),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "cases": len(outcomes),
        "retrieval_cases": len(hits),
        "tool_cases": len(tools),
    }


def check_thresholds(metrics: dict[str, Any], thresholds: dict[str, float]) -> dict[str, bool]:
    return {name: metrics[name] >= minimum for name, minimum in thresholds.items()}


class EvalRunner:
    def __init__(
        self, chat: ChatService, thresholds: dict[str, float], embedder: str, llm: str
    ) -> None:
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
            outcomes.append(score_case(case, result))
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


def format_report(record: EvalRunRecord) -> str:
    rows = [("metric", "value", "minimum", "status")]
    for name, minimum in record.thresholds.items():
        value = record.metrics[name]
        rows.append((name, f"{value:.3f}", f"{minimum:.2f}", "ok" if value >= minimum else "FAIL"))
    for name in ("recall_at_3", "latency_p50_ms", "latency_p95_ms"):
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
