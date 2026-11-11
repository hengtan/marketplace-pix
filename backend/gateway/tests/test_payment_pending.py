from __future__ import annotations

from uuid import uuid4

import pytest
from marketplace_common.security import verify_principal

from tests.auth_helpers import SECRET, Issuer, World, call
from tests.test_auth import bearer, make_settings


@pytest.fixture
def world() -> World:
    return World(Issuer())


async def lookup(world: World, headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return await call(
        world, "GET", f"/api/payments/by-order/{uuid4()}", make_settings(), headers=headers or {}
    )


async def test_an_existing_order_without_a_payment_yet_answers_202_with_retry_after(
    world: World,
) -> None:
    world.payment_status = 404
    response = await lookup(world, bearer(world.issuer.token(("customer",))))
    assert response.status_code == 202
    assert response.headers["retry-after"] == "1"
    body = response.json()
    assert body["detail"] == "payment is being created"
    assert body["retry_after_seconds"] == 1


async def test_the_order_is_confirmed_with_the_identity_of_the_caller(world: World) -> None:
    world.payment_status = 404
    await lookup(world, bearer(world.issuer.token(("customer",))))
    (check,) = world.upstream("ordering")
    principal = verify_principal(SECRET, dict(check.headers), check.headers["x-request-id"])
    assert principal is not None


async def test_a_guest_order_without_a_payment_yet_is_also_pending(world: World) -> None:
    world.payment_status = 404
    response = await lookup(world)
    assert response.status_code == 202
    (check,) = world.upstream("ordering")
    assert "x-user-id" not in check.headers


async def test_an_order_that_does_not_exist_or_is_not_the_callers_is_404(world: World) -> None:
    world.payment_status = 404
    world.order_status = 404
    response = await lookup(world, bearer(world.issuer.token(("customer",))))
    assert response.status_code == 404
    assert "retry-after" not in response.headers
    assert world.upstream("payments") == []


async def test_an_existing_payment_is_returned_untouched(world: World) -> None:
    response = await lookup(world, bearer(world.issuer.token(("customer",))))
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_other_payment_errors_are_not_masked_as_pending(world: World) -> None:
    world.payment_status = 500
    response = await lookup(world)
    assert response.status_code == 500
