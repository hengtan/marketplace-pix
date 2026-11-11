import asyncio
import json
import logging

from assistant.config import load_settings
from assistant.domain.errors import UpstreamUnavailable
from assistant.infrastructure.db.session import build_engine
from assistant.wiring import build_container


async def run() -> dict[str, int]:
    settings = load_settings()
    engine = build_engine(settings.database_url)
    try:
        container = build_container(settings, engine)
        try:
            return (await container.ingest.execute()).to_dict()
        finally:
            await container.aclose()
    finally:
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        report = asyncio.run(run())
    except UpstreamUnavailable as exc:
        raise SystemExit(f"catalog unavailable: {exc}") from None
    print(json.dumps(report))


if __name__ == "__main__":
    main()
