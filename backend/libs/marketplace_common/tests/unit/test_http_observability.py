from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from marketplace_common.observability import get_request_id, install_api_observability


def build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def item(item_id: int) -> dict[str, str | int | None]:
        return {"id": item_id, "request_id": get_request_id()}

    @app.get("/boom")
    async def boom() -> None:
        raise HTTPException(status_code=503, detail="down")

    install_api_observability(app, "demo")
    return app


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_metrics_endpoint_exposes_red_series_with_route_templates():
    client = TestClient(build_app())
    before = sample("http_requests_total", method="GET", route="/items/{item_id}", status="200")

    client.get("/items/1")
    client.get("/items/2")
    client.get("/boom")
    body = client.get("/metrics").text

    assert "http_request_duration_seconds_bucket" in body
    assert 'route="/items/{item_id}"' in body
    assert 'route="/boom"' in body
    assert (
        sample("http_requests_total", method="GET", route="/items/{item_id}", status="200") - before
        == 2
    )
    assert sample("http_requests_total", method="GET", route="/boom", status="503") >= 1
    assert (
        sample("http_request_duration_seconds_count", method="GET", route="/items/{item_id}") >= 2
    )


def test_metrics_endpoint_does_not_count_itself():
    client = TestClient(build_app())
    client.get("/metrics")
    client.get("/metrics")

    assert sample("http_requests_total", method="GET", route="/metrics", status="200") == 0


def test_unknown_paths_share_a_single_label():
    client = TestClient(build_app())
    client.get("/nope/1")
    client.get("/nope/2")

    assert sample("http_requests_total", method="GET", route="unmatched", status="404") >= 2


def test_request_id_is_reused_or_generated_and_returned():
    client = TestClient(build_app())

    given = client.get("/items/1", headers={"X-Request-Id": "abc-123"})
    generated = client.get("/items/1")

    assert given.headers["x-request-id"] == "abc-123"
    assert given.json()["request_id"] == "abc-123"
    assert len(generated.headers["x-request-id"]) == 32
    assert generated.json()["request_id"] == generated.headers["x-request-id"]


def test_invalid_request_id_is_replaced():
    client = TestClient(build_app())

    response = client.get("/items/1", headers={"X-Request-Id": "x" * 100})

    assert len(response.headers["x-request-id"]) == 32


async def test_install_api_observability_enforces_the_deadline_header() -> None:
    import httpx
    from fastapi import FastAPI

    from marketplace_common.observability import install_api_observability

    app = FastAPI()
    install_api_observability(app, "deadline-test")

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/ping")).status_code == 200
        assert (await c.get("/ping", headers={"X-Request-Deadline": "0"})).status_code == 504


def test_routes_from_included_routers_keep_their_template_instead_of_unmatched():
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/orders/{order_id}")
    async def order(order_id: int) -> dict[str, int]:
        return {"id": order_id}

    @router.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    app.include_router(router, prefix="/v2")
    install_api_observability(app, "demo-included")
    client = TestClient(app)

    client.get("/orders/7")
    client.get("/v2/orders/8")
    client.get("/v2/ping")
    client.get("/does-not-exist")
    body = client.get("/metrics").text

    assert 'route="/orders/{order_id}"' in body
    assert 'route="/v2/orders/{order_id}"' in body
    assert 'route="/v2/ping"' in body
    assert 'route="/orders/7"' not in body
    assert sample("http_requests_total", method="GET", route="unmatched", status="404") >= 1
