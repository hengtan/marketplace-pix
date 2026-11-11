import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: list[str] = field(default_factory=list)


def load_json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def check_gate(
    metrics: dict[str, Any],
    minimums: dict[str, float],
    baseline: dict[str, float] | None = None,
    tolerance: float = 0.02,
    lower_is_better: frozenset[str] = frozenset({"latency_p95_ms"}),
) -> GateResult:
    """Fails when a metric is under its absolute floor or drops more than `tolerance` below
    the recorded baseline, so quality can only move forward on purpose."""
    failures: list[str] = []
    for name, floor in minimums.items():
        value = metrics.get(name)
        if value is None:
            failures.append(f"{name}: metric missing")
        elif value < floor:
            failures.append(f"{name}: {value:.3f} below minimum {floor:.3f}")
    for name, reference in (baseline or {}).items():
        value = metrics.get(name)
        if value is None or name in lower_is_better:
            continue
        if value < reference - tolerance:
            failures.append(
                f"{name}: {value:.3f} regressed from baseline {reference:.3f} "
                f"(tolerance {tolerance:.2f})"
            )
    return GateResult(not failures, failures)


def baseline_from(metrics: dict[str, Any], names: list[str]) -> dict[str, float]:
    return {name: float(metrics[name]) for name in names}
