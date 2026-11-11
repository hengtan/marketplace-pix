import asyncio
import json
import random
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from marketplace_common.messaging import IncomingEvent
from marketplace_common.resilience import (
    BreakerConfig,
    BreakerState,
    CircuitBreaker,
    Deadline,
    deadline_scope,
)

from payments.application.errors import PspUnavailable
from payments.application.handle_order_event import HandleOrderEvent
from payments.application.ports import ChargeStatus
from payments.domain.money import Money
from payments.infrastructure.psp.resilient import ResilientPsp
from payments.interface.api import create_app
from payments.interface.webhook_security import sign
from tests.fakes import FakeDatabase, FakePsp, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
SECRET = "s"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class NoSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class FlakyPsp(FakePsp):
    def __init__(self, failures: int = 0, error: Exception | None = None) -> None:
        super().__init__()
        self.status_failures = failures
        self.status_calls = 0
        self.error = error or ConnectionError("psp down")
        self.hang = False

    async def get_charge_status(self, charge_id: str) -> ChargeStatus:
        self.status_calls += 1
        if self.hang:
            await asyncio.sleep(60)
        if self.status_calls <= self.status_failures:
            raise self.error
        return await super().get_charge_status(charge_id)


def wrap(inner: FlakyPsp, clock: Clock | None = None, **kwargs) -> ResilientPsp:  # type: ignore[no-untyped-def]
    clock = clock or Clock()
    breaker = CircuitBreaker(
        f"psp-test-{uuid4().hex[:6]}",
        BreakerConfig(minimum_calls=3, window_size=6, open_seconds=5.0, half_open_max_calls=1),
        clock=clock,
        is_failure=lambda e: not isinstance(e, kwargs.get("neutral_errors", ())),
    )
    return ResilientPsp(
        inner, breaker=breaker, sleeper=NoSleep(), rng=random.Random(1), timeout=0.05, **kwargs
    )


async def seeded() -> tuple[FlakyPsp, str]:
    psp = FlakyPsp()
    charge = await psp.create_charge("o1", Money(1000, "BRL"), NOW)
    return psp, charge.id


async def test_transient_status_failures_are_retried() -> None:
    psp, charge_id = await seeded()
    psp.status_failures = 2
    assert await wrap(psp).get_charge_status(charge_id) is ChargeStatus.PENDING
    assert psp.status_calls == 3


async def test_gives_up_with_psp_unavailable_after_the_retries() -> None:
    psp, charge_id = await seeded()
    psp.status_failures = 99
    with pytest.raises(PspUnavailable):
        await wrap(psp).get_charge_status(charge_id)
    assert psp.status_calls == 3


async def test_breaker_opens_and_stops_hitting_the_psp() -> None:
    psp, charge_id = await seeded()
    psp.status_failures = 99
    clock = Clock()
    resilient = wrap(psp, clock)
    with pytest.raises(PspUnavailable):
        await resilient.get_charge_status(charge_id)
    assert resilient.breaker.state is BreakerState.OPEN
    calls = psp.status_calls
    with pytest.raises(PspUnavailable) as info:
        await resilient.get_charge_status(charge_id)
    assert psp.status_calls == calls and info.value.retry_after_seconds >= 1
    clock.now += 5
    psp.status_failures = 0
    assert await resilient.get_charge_status(charge_id) is ChargeStatus.PENDING
    assert resilient.breaker.state is BreakerState.CLOSED


async def test_slow_psp_is_cut_by_the_timeout() -> None:
    psp, charge_id = await seeded()
    psp.hang = True
    with pytest.raises(PspUnavailable):
        await wrap(psp).get_charge_status(charge_id)


async def test_remaining_deadline_caps_the_timeout() -> None:
    psp, charge_id = await seeded()
    psp.hang = True
    resilient = wrap(psp)
    resilient._timeout = 30.0
    with deadline_scope(Deadline.after(0.02)), pytest.raises(PspUnavailable):
        await resilient.get_charge_status(charge_id)


async def test_neutral_errors_pass_through_without_retry_or_breaker_failure() -> None:
    class NotFound(Exception):
        pass

    psp, charge_id = await seeded()
    psp.status_failures = 99
    psp.error = NotFound()
    clock = Clock()
    resilient = wrap(psp, clock, neutral_errors=(NotFound,))
    for _ in range(5):
        with pytest.raises(NotFound):
            await resilient.get_charge_status(charge_id)
    assert psp.status_calls == 5 and resilient.breaker.state is BreakerState.CLOSED


async def test_create_and_cancel_are_retried_because_they_are_idempotent() -> None:
    psp = FlakyPsp()
    calls = {"n": 0}
    original = psp.create_charge

    async def flaky_create(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("blip")
        return await original(*args, **kwargs)

    psp.create_charge = flaky_create  # type: ignore[method-assign]
    charge = await wrap(psp).create_charge("o9", Money(500, "BRL"), NOW)
    assert calls["n"] == 3 and psp.charges == 1
    assert await wrap(psp).cancel_charge(charge.id) is True


async def test_webhook_answers_503_with_retry_after_while_the_psp_is_down() -> None:
    db, inner, clock = FakeDatabase(), FlakyPsp(), Clock()
    order_id = uuid4()
    await HandleOrderEvent(lambda: FakeUow(db), inner, clock=lambda: NOW).handle(
        IncomingEvent(
            uuid4(),
            "OrderCreated",
            str(order_id),
            {"order_id": str(order_id), "total_cents": 4480, "currency": "BRL"},
        )
    )
    charge_id = inner.by_reference[str(order_id)].id
    inner.statuses[charge_id] = ChargeStatus.PAID
    inner.status_failures = 99
    app = create_app(uow_factory=lambda: FakeUow(db), psp=wrap(inner, clock), webhook_secret=SECRET)
    body = json.dumps({"event": "charge.paid", "charge_id": charge_id}).encode()
    headers = {"X-Signature": sign(SECRET, body)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        down = await c.post("/webhooks/psp", content=body, headers=headers)
        assert all(p.status.value == "PENDING" for p in db.payments.values())
        inner.status_failures = 0
        clock.now += 5
        recovered = await c.post("/webhooks/psp", content=body, headers=headers)
    assert down.status_code == 503 and down.headers["retry-after"].isdigit()
    assert down.json()["code"] == "psp_unavailable"
    assert recovered.status_code == 200 and recovered.json() == {"status": "confirmed"}
    assert all(p.status.value == "CONFIRMED" for p in db.payments.values())
