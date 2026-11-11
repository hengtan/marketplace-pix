import argparse
import asyncio
import json
import logging
from pathlib import Path

from assistant.application.evaluation import EvalRunner, format_report, load_cases
from assistant.application.gate import baseline_from, check_gate, load_json
from assistant.config import Settings, load_settings
from assistant.infrastructure.db.session import build_engine
from assistant.infrastructure.fixtures import (
    EmptyOrderGateway,
    FixtureInventoryGateway,
    SnapshotCatalogGateway,
)
from assistant.infrastructure.judges.heuristic import HeuristicJudge
from assistant.wiring import build_container


def thresholds(settings: Settings) -> dict[str, float]:
    return {
        "hit_at_3": settings.eval_min_hit_at_3,
        "mrr": settings.eval_min_mrr,
        "groundedness": settings.eval_min_groundedness,
        "tool_accuracy": settings.eval_min_tool_accuracy,
        "answer_pass": settings.eval_min_answer_pass,
    }


EVALS_DIR = Path("evals")
BASELINE_METRICS = [
    "hit_at_1", "hit_at_3", "hit_at_5", "mrr", "ndcg_at_5", "context_precision",
    "context_recall", "negation_pass", "faithfulness", "answer_relevancy", "groundedness",
    "tool_accuracy", "answer_pass",
]  # fmt: skip


async def run(
    offline: bool,
    fixture: Path,
    cases_path: Path | None,
    gate: bool = False,
    update_baseline: bool = False,
) -> int:
    settings = load_settings()
    engine = build_engine(settings.database_url)
    try:
        if offline:
            catalog = SnapshotCatalogGateway(fixture)
            container = build_container(
                settings,
                engine,
                catalog=catalog,
                inventory=FixtureInventoryGateway(await catalog.list_products()),
                orders=EmptyOrderGateway(),
                token_delay_seconds=0.0,
            )
            await container.ingest.execute()
        else:
            container = build_container(settings, engine, token_delay_seconds=0.0)
        try:
            cases = load_cases(cases_path or Path(settings.evals_cases_path))
            runner = EvalRunner(
                container.chat,
                thresholds(settings),
                container.embedder.name,
                container.llm.name,
                HeuristicJudge(),
            )
            record = await runner.run(cases)
            await container.eval_store.save(record)
        finally:
            await container.aclose()
    finally:
        await engine.dispose()
    print(format_report(record))
    if update_baseline:
        (EVALS_DIR / "baseline.json").write_text(
            json.dumps(baseline_from(record.metrics, BASELINE_METRICS), indent=2) + "\n"
        )
        print("baseline updated")
    if not gate:
        return 0 if record.passed else 1
    verdict = check_gate(
        record.metrics,
        load_json(EVALS_DIR / "thresholds.json"),
        load_json(EVALS_DIR / "baseline.json"),
        float(load_json(EVALS_DIR / "gate.json")["tolerance"]),
    )
    for failure in verdict.failures:
        print(f"GATE FAIL {failure}")
    print("GATE: " + ("PASS" if verdict.passed else "FAIL"))
    return 0 if verdict.passed and record.passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m assistant.evals")
    parser.add_argument("--offline", action="store_true", help="use the catalog snapshot")
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/catalog.json"))
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--gate", action="store_true", help="fail on regression vs baseline")
    parser.add_argument(
        "--update-baseline", action="store_true", help="rewrite evals/baseline.json"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    code = asyncio.run(run(args.offline, args.fixture, args.cases, args.gate, args.update_baseline))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
