import json
from uuid import UUID, uuid4

import httpx
import pytest

from assistant.application.ports import OrderInfo, StockInfo
from assistant.application.prompt import PromptBuilder
from assistant.application.tools import GetOrderStatusTool, GetStockTool
from assistant.domain.errors import ToolError, UpstreamUnavailable
from assistant.domain.models import CatalogProduct
from assistant.infrastructure.embedders.ollama import OllamaEmbedder
from assistant.infrastructure.http.gateways import HttpInventoryGateway, HttpOrderGateway
from assistant.infrastructure.llm.mock import MockLlm
from assistant.infrastructure.llm.ollama import OllamaLlm
from tests.helpers import passage, pid


class FakeInventory:
    def __init__(self, stock: StockInfo | None, fail: bool = False) -> None:
        self._stock, self._fail = stock, fail

    async def get_stock(self, product_id: UUID) -> StockInfo | None:
        if self._fail:
            raise UpstreamUnavailable("down")
        return self._stock


class FakeCatalog:
    async def get_product(self, product_id: UUID) -> CatalogProduct | None:
        return CatalogProduct(product_id, "s", "Produto Y", "d", 100, "casa", 4.0, 1, (), "m")


class FakeOrders:
    def __init__(self, order: OrderInfo | None, fail: bool = False) -> None:
        self._order, self._fail = order, fail

    async def get_order(self, order_id: UUID) -> OrderInfo | None:
        if self._fail:
            raise UpstreamUnavailable("down")
        return self._order


async def test_get_stock_resolves_name_and_returns_summary() -> None:
    product_id = pid("x")
    tool = GetStockTool(FakeInventory(StockInfo(product_id, 3, 1)), FakeCatalog())  # type: ignore[arg-type]
    result = await tool.run({"product_id": str(product_id)})
    assert result.ok and result.data["name"] == "Produto Y" and result.data["available"] == 3


async def test_get_stock_upstream_failure_is_a_friendly_failed_result() -> None:
    tool = GetStockTool(FakeInventory(None, fail=True), FakeCatalog())  # type: ignore[arg-type]
    result = await tool.run({"product_id": str(uuid4())})
    assert not result.ok and "Não consegui" in result.summary


async def test_get_stock_rejects_bad_arguments() -> None:
    tool = GetStockTool(FakeInventory(None), FakeCatalog())  # type: ignore[arg-type]
    with pytest.raises(ToolError):
        await tool.run({"product_id": "not-a-uuid"})


async def test_order_status_summary_has_no_personal_data() -> None:
    order_id = uuid4()
    info = OrderInfo(order_id, "PAID", 12990, "BRL", 2, "2026-11-01T10:00:00Z", None)
    result = await GetOrderStatusTool(FakeOrders(info)).run({"order_id": str(order_id)})  # type: ignore[arg-type]
    assert result.ok
    assert set(result.data) == {
        "order_id",
        "status",
        "total_cents",
        "items_count",
        "created_at",
        "cancel_reason",
    }


async def test_order_not_found_and_upstream_down() -> None:
    order_id = str(uuid4())
    missing = await GetOrderStatusTool(FakeOrders(None)).run({"order_id": order_id})  # type: ignore[arg-type]
    down = await GetOrderStatusTool(FakeOrders(None, fail=True)).run({"order_id": order_id})  # type: ignore[arg-type]
    assert not missing.ok and "Não encontrei" in missing.summary
    assert not down.ok and "Não consegui" in down.summary


async def test_http_gateways_map_status_codes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/stock/"):
            body = {"product_id": request.url.path[7:], "available": 7, "reserved": 2}
            return httpx.Response(200, json=body)
        if request.url.path == "/orders/slow":
            raise httpx.ConnectTimeout("slow")
        if request.url.path.endswith("0000"):
            return httpx.Response(404, json={"detail": "order not found"})
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    inventory = HttpInventoryGateway(client, "http://inv")
    stock = await inventory.get_stock(uuid4())
    assert stock is not None and stock.available == 7 and stock.reserved == 2

    orders = HttpOrderGateway(client, "http://ord")
    assert await orders.get_order(UUID(int=0)) is None
    with pytest.raises(UpstreamUnavailable):
        await orders.get_order(uuid4())


async def test_ollama_embedder_parses_response_and_checks_dimension() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "nomic" and body["input"] == ["a", "b"]
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    embedder = OllamaEmbedder(client, "nomic", 3, "http://ollama")
    assert await embedder.embed(["a", "b"]) == [[0.1, 0.2, 0.3], [0.3, 0.2, 0.1]]
    assert embedder.name == "ollama-nomic-3"
    with pytest.raises(UpstreamUnavailable):
        await OllamaEmbedder(client, "nomic", 4, "http://ollama").embed(["a", "b"])


async def test_ollama_llm_generate_and_stream() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][0]["role"] == "system"
        if body["stream"]:
            lines = [
                json.dumps({"message": {"content": "Olá "}, "done": False}),
                json.dumps({"message": {"content": "mundo"}, "done": False}),
                json.dumps({"message": {"content": ""}, "done": True}),
            ]
            return httpx.Response(200, content="\n".join(lines))
        return httpx.Response(200, json={"message": {"content": "Olá mundo"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = OllamaLlm(client, "llama", "http://ollama")
    prompt = PromptBuilder().build("oi", [passage()], [])
    assert await llm.generate(prompt) == "Olá mundo"
    assert "".join([t async for t in llm.stream(prompt)]) == "Olá mundo"
    assert llm.name == "ollama-llama"
    assert MockLlm().name == "mock"


async def test_ollama_down_raises_upstream_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamUnavailable):
        await OllamaLlm(client, "llama", "http://ollama").generate(
            PromptBuilder().build("oi", [], [])
        )
