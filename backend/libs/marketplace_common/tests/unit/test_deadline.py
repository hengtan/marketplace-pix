import httpx
import pytest
from fastapi import FastAPI

from marketplace_common.resilience import (
    DEADLINE_HEADER,
    Deadline,
    DeadlineExceeded,
    cap_timeout,
    check_deadline,
    current_deadline,
    deadline_event_hooks,
    deadline_scope,
    install_deadline,
    outbound_headers,
)
from tests.unit.fakes import FakeClock


def test_remaining_shrinks_with_the_clock_and_expires() -> None:
    clock = FakeClock()
    deadline = Deadline.after(2.0, clock)
    assert deadline.remaining() == 2.0 and not deadline.expired
    clock.advance(1.5)
    assert deadline.remaining() == pytest.approx(0.5)
    clock.advance(0.5)
    assert deadline.expired and deadline.remaining() == 0.0
    with pytest.raises(DeadlineExceeded):
        deadline.check("test")


def test_header_carries_the_remaining_budget_in_milliseconds() -> None:
    clock = FakeClock()
    deadline = Deadline.after(3.0, clock)
    clock.advance(0.5)
    assert deadline.header_value() == "2500"
    assert deadline.header_value(reserve=0.1) == "2400"


@pytest.mark.parametrize("raw", [None, "", "abc", "nan", "inf", "-inf"])
def test_invalid_headers_are_ignored(raw: str | None) -> None:
    assert Deadline.parse(raw, FakeClock()) is None


def test_negative_header_means_already_expired() -> None:
    assert Deadline.parse("-5", FakeClock()).expired  # type: ignore[union-attr]


def test_timeout_is_capped_and_reserves_time_for_the_caller() -> None:
    deadline = Deadline.after(2.0, FakeClock())
    assert deadline.timeout() == 2.0
    assert deadline.timeout(cap=0.5) == 0.5
    assert deadline.timeout(cap=5.0, reserve=0.5) == 1.5
    assert deadline.timeout(reserve=10) == 0.0


def test_tighten_never_extends() -> None:
    clock = FakeClock()
    deadline = Deadline.after(2.0, clock)
    assert deadline.tighten(10.0).remaining() == 2.0
    assert deadline.tighten(1.0).remaining() == 1.0


def test_context_helpers() -> None:
    clock = FakeClock()
    assert current_deadline() is None and cap_timeout(3.0) == 3.0 and outbound_headers() == {}
    check_deadline()
    with deadline_scope(Deadline.after(1.0, clock)):
        assert cap_timeout(3.0) == 1.0
        assert outbound_headers() == {DEADLINE_HEADER: "1000"}
        clock.advance(2.0)
        with pytest.raises(DeadlineExceeded):
            check_deadline("scope")
    assert current_deadline() is None


def build_app(clock: FakeClock, **kwargs: float) -> FastAPI:
    app = FastAPI()
    install_deadline(app, **kwargs)

    @app.get("/remaining")
    async def remaining() -> dict[str, float | None]:
        deadline = current_deadline()
        return {"remaining": None if deadline is None else deadline.remaining()}

    @app.get("/raise")
    async def raiser() -> None:
        raise DeadlineExceeded

    return app


async def get(app: FastAPI, path: str, **headers: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path, headers=headers)


async def test_middleware_adopts_the_incoming_deadline() -> None:
    response = await get(build_app(FakeClock()), "/remaining", **{DEADLINE_HEADER: "1500"})
    assert 1.0 < response.json()["remaining"] <= 1.5


async def test_middleware_rejects_requests_that_arrive_expired() -> None:
    response = await get(build_app(FakeClock()), "/remaining", **{DEADLINE_HEADER: "0"})
    assert response.status_code == 504 and response.json() == {
        "detail": "request deadline exceeded"
    }


async def test_middleware_applies_default_and_ceiling() -> None:
    app = build_app(FakeClock(), default_seconds=2.0, max_seconds=3.0)
    assert 1.0 < (await get(app, "/remaining")).json()["remaining"] <= 2.0
    capped = (await get(app, "/remaining", **{DEADLINE_HEADER: "60000"})).json()["remaining"]
    assert 2.0 < capped <= 3.0


async def test_no_deadline_when_nothing_is_configured() -> None:
    assert (await get(build_app(FakeClock()), "/remaining")).json() == {"remaining": None}


async def test_deadline_exceeded_inside_a_handler_becomes_504() -> None:
    response = await get(build_app(FakeClock()), "/raise")
    assert response.status_code == 504


async def test_http_client_hook_forwards_header_and_clamps_timeouts() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    clock = FakeClock()
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=10.0, event_hooks=deadline_event_hooks()
    ) as client:
        await client.get("http://x/a")
        with deadline_scope(Deadline.after(1.0, clock)):
            await client.get("http://x/b")
            clock.advance(2.0)
            with pytest.raises(DeadlineExceeded):
                await client.get("http://x/c")
    assert DEADLINE_HEADER not in seen[0].headers
    assert seen[1].headers[DEADLINE_HEADER] == "1000"
    assert seen[1].extensions["timeout"]["read"] == 1.0
    assert len(seen) == 2
