import argparse
import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from assistant.application.evaluation import load_cases
from assistant.config import load_settings
from assistant.infrastructure.db.session import build_engine
from assistant.infrastructure.fixtures import (
    EmptyOrderGateway,
    FixtureInventoryGateway,
    SnapshotCatalogGateway,
)
from assistant.wiring import build_container

PASSES: list[tuple[str, Callable[[str], str]]] = [
    ("1. primeira vez", lambda q: q),
    ("2. mesma pergunta", lambda q: q),
    ("3. caixa alta e pontuacao", lambda q: q.upper() + "!!"),
    ("4. com cortesia", lambda q: f"por favor, {q}, obrigado"),
]


async def run(fixture: Path, cases_path: Path) -> str:
    settings = load_settings().model_copy(update={"cache_enabled": True})
    engine = build_engine(settings.database_url)
    catalog = SnapshotCatalogGateway(fixture)
    container = build_container(
        settings,
        engine,
        catalog=catalog,
        inventory=FixtureInventoryGateway(await catalog.list_products()),
        orders=EmptyOrderGateway(),
        token_delay_seconds=0.0,
    )
    questions = [c.question for c in load_cases(cases_path) if not c.history]
    rows = ["| passada | consultas | hits | misses | ignoradas | hit rate | tokens economizados |"]
    rows.append("|---|---|---|---|---|---|---|")
    try:
        await container.ingest.execute()
        await container.cache.invalidate_all()
        for name, transform in PASSES:
            before = (
                container.cache.stats.hits,
                container.cache.stats.misses,
                container.cache.stats.skips,
                container.cache.stats.tokens_saved,
            )
            for question in questions:
                await container.chat.chat(uuid4(), transform(question))
            stats = container.cache.stats
            hits, misses, skips = (
                stats.hits - before[0],
                stats.misses - before[1],
                stats.skips - before[2],
            )
            rate = hits / (hits + misses) if hits + misses else 0.0
            rows.append(
                f"| {name} | {len(questions)} | {hits} | {misses} | {skips} | {rate:.3f} | "
                f"{stats.tokens_saved - before[3]} |"
            )
        stats = container.cache.stats
        rows.append("")
        rows.append(
            f"Total: hit rate {stats.hit_rate:.3f}, {stats.tokens_saved} tokens e "
            f"US$ {stats.cost_saved_usd:.4f} economizados (preco de referencia)."
        )
    finally:
        await container.cache.invalidate_all()
        await container.aclose()
        await engine.dispose()
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m assistant.cachebench")
    parser.add_argument("--fixture", type=Path, default=Path("tests/fixtures/catalog.json"))
    parser.add_argument("--cases", type=Path, default=Path("evals/cases.yaml"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    print(asyncio.run(run(args.fixture, args.cases)))


if __name__ == "__main__":
    main()
