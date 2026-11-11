import argparse
import asyncio
import logging
from pathlib import Path

from assistant.application.evaluation import EvalRunner, format_report, load_cases
from assistant.config import Settings, load_settings
from assistant.infrastructure.db.session import build_engine
from assistant.infrastructure.fixtures import (
    EmptyOrderGateway,
    FixtureInventoryGateway,
    SnapshotCatalogGateway,
)
from assistant.wiring import build_container


def thresholds(settings: Settings) -> dict[str, float]:
    return {
        "hit_at_3": settings.eval_min_hit_at_3,
        "mrr": settings.eval_min_mrr,
        "groundedness": settings.eval_min_groundedness,
        "tool_accuracy": settings.eval_min_tool_accuracy,
        "answer_pass": settings.eval_min_answer_pass,
    }


async def run(offline: bool, fixture: Path, cases_path: Path | None) -> int:
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
                container.chat, thresholds(settings), container.embedder.name, container.llm.name
            )
            record = await runner.run(cases)
            await container.eval_store.save(record)
        finally:
            await container.aclose()
    finally:
        await engine.dispose()
    print(format_report(record))
    return 0 if record.passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m assistant.evals")
    parser.add_argument("--offline", action="store_true", help="use the catalog snapshot")
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/catalog.json"))
    parser.add_argument("--cases", type=Path, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    raise SystemExit(asyncio.run(run(args.offline, args.fixture, args.cases)))


if __name__ == "__main__":
    main()
