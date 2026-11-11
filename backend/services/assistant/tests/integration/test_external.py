import socket

import pytest

from assistant.config import Settings
from assistant.wiring import build_container
from tests.integration.conftest import TEST_DB

pytestmark = pytest.mark.external


def _up(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("localhost", port)) == 0


requires_services = pytest.mark.skipif(
    not (_up(8003) and _up(8004)), reason="catalog (8003) and inventory (8004) are not running"
)


@pytest.fixture
async def live(engine):  # type: ignore[no-untyped-def]
    settings = Settings(assistant_db=TEST_DB)  # type: ignore[call-arg]
    container = build_container(settings, engine, token_delay_seconds=0.0)
    yield container
    await container.aclose()


@requires_services
async def test_end_to_end_question_against_the_real_catalog(live) -> None:  # type: ignore[no-untyped-def]
    report = await live.ingest.execute()
    assert report.indexed > 0
    result = await live.chat.chat(None, "quero um fone com cancelamento de ruído")
    assert "Fone Bluetooth Nova ANC" in result.answer
    assert result.citations[0].slug == "fone-bluetooth-nova"
    assert [t.name for t in result.tool_calls] == ["search_products"]


@requires_services
async def test_stock_tool_hits_the_real_inventory(live) -> None:  # type: ignore[no-untyped-def]
    await live.ingest.execute()
    result = await live.chat.chat(None, "tem estoque do relógio GPS?")
    assert [t.name for t in result.tool_calls] == ["search_products", "get_stock"]
    assert "Relógio GPS Trail" in result.answer and "unidades" in result.answer
    assert all(t.ok for t in result.tool_calls)
