from uuid import uuid4

import httpx
import pytest

from ordering.application.errors import CatalogUnavailable
from ordering.infrastructure.catalog.http_catalog import HttpCatalogGateway


def product(pid, price=1990):
    return {
        "id": str(pid),
        "name": "Fone",
        "price_cents": price,
        "currency": "BRL",
        "merchant": {"id": str(uuid4()), "slug": "aurora-tech", "name": "Aurora Tech"},
    }


def gateway(handler, attempts=2):
    return HttpCatalogGateway(
        "http://catalog", attempts=attempts, transport=httpx.MockTransport(handler)
    )


async def test_maps_products_from_the_catalog_contract():
    pid = uuid4()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[product(pid, 34990)])

    (found,) = await gateway(handler).get_products([pid])

    assert found.id == pid and found.price_cents == 34990 and found.currency == "BRL"
    assert seen["url"] == f"http://catalog/products/by-ids?ids={pid}"


async def test_missing_products_are_simply_not_returned():
    assert await gateway(lambda r: httpx.Response(200, json=[])).get_products([uuid4()]) == []


async def test_retries_once_on_server_error_then_succeeds():
    pid, calls = uuid4(), {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, json=[product(pid)])

    assert len(await gateway(handler).get_products([pid])) == 1
    assert calls["n"] == 2


async def test_persistent_failure_becomes_catalog_unavailable():
    with pytest.raises(CatalogUnavailable):
        await gateway(lambda r: httpx.Response(500)).get_products([uuid4()])


async def test_network_error_becomes_catalog_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(CatalogUnavailable):
        await gateway(handler).get_products([uuid4()])


async def test_malformed_payload_becomes_catalog_unavailable():
    with pytest.raises(CatalogUnavailable):
        await gateway(lambda r: httpx.Response(200, json=[{"id": "x"}])).get_products([uuid4()])


async def test_accepts_the_paginated_envelope_returned_by_the_real_catalog():
    pid = uuid4()
    envelope = {"items": [product(pid, 12990)], "total": 1, "page": 1, "page_size": 1}

    (found,) = await gateway(lambda r: httpx.Response(200, json=envelope)).get_products([pid])

    assert found.id == pid and found.price_cents == 12990
