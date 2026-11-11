from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from marketplace_common.security import verify_principal

from gateway.app import create_app
from gateway.config import Settings
from tests.auth_helpers import AUDIENCE, ISSUER, SECRET, Issuer, World, call

UPSTREAMS = {
    n: f"http://{n}"
    for n in (
        "catalog",
        "inventory",
        "ordering",
        "payments",
        "ledger",
        "notifications",
        "assistant",
        "identity",
    )
}


def make_settings(**overrides: object) -> Settings:
    base = {f"{name}_url": url for name, url in UPSTREAMS.items()}
    merged = {"internal_auth_secret": SECRET, **base, **overrides}
    return Settings(_env_file=None, **merged)  # type: ignore[arg-type]


@pytest.fixture
def world() -> World:
    return World(Issuer())


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_valid_token_reaches_the_upstream_as_a_signed_identity(world: World) -> None:
    user = uuid4()
    merchant = uuid4()
    token = world.issuer.token(("merchant",), user_id=user, merchant_id=merchant)
    response = await call(
        world,
        "GET",
        f"/api/ledger/merchants/{merchant}/summary",
        make_settings(),
        headers={**bearer(token), "x-request-id": "rid-1"},
    )
    assert response.status_code == 200
    forwarded = world.upstream("ledger")[0]
    principal = verify_principal(SECRET, dict(forwarded.headers), forwarded.headers["x-request-id"])
    assert principal is not None
    assert principal.user_id == user
    assert principal.merchant_id == merchant
    assert principal.roles == frozenset({"merchant"})
    assert "authorization" not in forwarded.headers


@pytest.mark.parametrize("path", ["/api/catalog/products", "/api/orders/abc"])
async def test_client_supplied_identity_headers_never_reach_upstreams(
    world: World, path: str
) -> None:
    forged = {
        "X-User-Id": str(uuid4()),
        "x-user-roles": "admin",
        "X-User-Scopes": "ledger:read:any users:manage",
        "X-Merchant-Id": str(uuid4()),
        "X-Auth-Ts": str(int(time.time())),
        "X-Auth-Sig": "deadbeef",
    }
    response = await call(world, "GET", path, make_settings(), headers=forged)
    assert response.status_code == 200
    forwarded = next(r for r in world.requests if r.url.host in {"catalog", "ordering"})
    for name in forged:
        assert name.lower() not in forwarded.headers


async def test_forged_headers_are_replaced_by_the_real_identity(world: World) -> None:
    real = uuid4()
    token = world.issuer.token(("customer",), user_id=real)
    headers = {**bearer(token), "X-User-Id": str(uuid4()), "X-User-Roles": "admin"}
    await call(world, "GET", "/api/orders/abc", make_settings(), headers=headers)
    forwarded = world.upstream("ordering")[0]
    principal = verify_principal(SECRET, dict(forwarded.headers), forwarded.headers["x-request-id"])
    assert principal is not None and principal.user_id == real and not principal.is_admin


async def test_forged_headers_are_stripped_even_with_auth_disabled(world: World) -> None:
    response = await call(
        world,
        "GET",
        "/api/catalog/products",
        make_settings(auth_enabled=False),
        headers={"X-User-Id": str(uuid4()), "X-User-Roles": "admin"},
    )
    assert response.status_code == 200
    assert "x-user-id" not in world.upstream("catalog")[0].headers


def forge_hs256(claims: dict[str, object], secret: bytes) -> str:
    def part(data: object) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signing_input = f"{part({'alg': 'HS256', 'typ': 'JWT', 'kid': 'key-1'})}.{part(claims)}"
    digest = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{base64.urlsafe_b64encode(digest).rstrip(b'=').decode()}"


def broken_tokens(world: World) -> dict[str, str]:
    other = Issuer("key-1")
    now = int(time.time())
    public_pem = world.issuer.private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    base = {"iss": ISSUER, "aud": AUDIENCE, "sub": str(uuid4()), "iat": now, "exp": now + 600}
    return {
        "expired": world.issuer.token(exp=now - 600, iat=now - 1200, nbf=now - 1200),
        "wrong_audience": world.issuer.token(aud="someone-else"),
        "wrong_issuer": world.issuer.token(iss="evil"),
        "signed_by_attacker": other.token(),
        "no_exp": jwt.encode(
            {k: v for k, v in base.items() if k != "exp"},
            world.issuer.private_key,
            algorithm="EdDSA",
            headers={"kid": "key-1"},
        ),
        "alg_none": jwt.encode(base, None, algorithm="none", headers={"kid": "key-1"}),
        "hs256_with_public_key": forge_hs256(base, public_pem),
        "unknown_kid": Issuer("rogue").token(),
        "garbage": "not.a.jwt",
        "missing_kid": jwt.encode(base, world.issuer.private_key, algorithm="EdDSA"),
    }


@pytest.mark.parametrize(
    "name",
    [
        "expired",
        "wrong_audience",
        "wrong_issuer",
        "signed_by_attacker",
        "no_exp",
        "alg_none",
        "hs256_with_public_key",
        "unknown_kid",
        "garbage",
        "missing_kid",
    ],
)
async def test_invalid_tokens_are_rejected_with_401(world: World, name: str) -> None:
    token = broken_tokens(world)[name]
    response = await call(world, "GET", "/api/orders/abc", make_settings(), headers=bearer(token))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert world.upstream("ordering") == []


async def test_malformed_authorization_header_is_401(world: World) -> None:
    response = await call(
        world, "GET", "/api/orders/abc", make_settings(), headers={"Authorization": "Basic abc"}
    )
    assert response.status_code == 401


async def test_public_routes_work_without_a_token_and_ignore_a_bad_one(world: World) -> None:
    anonymous = await call(world, "GET", "/api/catalog/products", make_settings())
    junk = await call(
        world, "GET", "/api/catalog/products", make_settings(), headers=bearer("junk")
    )
    assert anonymous.status_code == junk.status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/ledger/merchants/x/summary"),
        ("GET", "/api/ledger/accounts/merchant:x/entries"),
        ("GET", "/api/ledger/reconciliation"),
        ("PUT", "/api/inventory/stock/abc"),
        ("GET", "/api/inventory/stock/mine"),
        ("GET", "/api/orders/merchant"),
        ("GET", "/api/notifications"),
        ("GET", "/api/notifications/abc/preview"),
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/admin/users"),
        ("POST", "/api/assistant/admin/reindex"),
        ("POST", "/api/catalog/products"),
        ("PATCH", "/api/catalog/products/abc"),
        ("DELETE", "/api/catalog/products/abc"),
    ],
)
async def test_protected_routes_require_authentication(
    world: World, method: str, path: str
) -> None:
    response = await call(world, method, path, make_settings(enable_dev_routes=True), json={})
    assert response.status_code == 401


async def test_dev_payment_simulator_works_for_guest_checkout_when_dev_routes_are_on(
    world: World,
) -> None:
    path = "/api/payments/dev/psp/charges/ch/pay"
    on = await call(world, "POST", path, make_settings(enable_dev_routes=True), json={})
    off = await call(world, "POST", path, make_settings(enable_dev_routes=False), json={})
    assert on.status_code != 401
    assert off.status_code == 404


@pytest.mark.parametrize(
    ("method", "path", "roles", "expected"),
    [
        ("GET", "/api/ledger/merchants/x/summary", ("customer",), 403),
        ("GET", "/api/ledger/merchants/x/summary", ("merchant",), 200),
        ("GET", "/api/ledger/merchants/x/summary", ("admin",), 200),
        ("GET", "/api/ledger/reconciliation", ("merchant",), 403),
        ("GET", "/api/ledger/reconciliation", ("admin",), 200),
        ("PUT", "/api/inventory/stock/abc", ("customer",), 403),
        ("PUT", "/api/inventory/stock/abc", ("merchant",), 200),
        ("GET", "/api/inventory/stock/mine", ("customer",), 403),
        ("GET", "/api/inventory/stock/mine", ("merchant",), 200),
        ("GET", "/api/orders/merchant", ("customer",), 403),
        ("GET", "/api/orders/merchant", ("merchant",), 200),
        ("POST", "/api/auth/admin/users", ("merchant",), 403),
        ("POST", "/api/auth/admin/users", ("admin",), 200),
        ("POST", "/api/assistant/admin/reindex", ("customer",), 403),
        ("POST", "/api/assistant/admin/reindex", ("admin",), 200),
        ("POST", "/api/catalog/products", ("customer",), 403),
        ("POST", "/api/catalog/products", ("merchant",), 200),
        ("PATCH", "/api/catalog/products/abc", ("customer",), 403),
        ("PATCH", "/api/catalog/products/abc", ("merchant",), 200),
        ("DELETE", "/api/catalog/products/abc", ("admin",), 200),
    ],
)
async def test_role_based_authorization(
    world: World, method: str, path: str, roles: tuple[str, ...], expected: int
) -> None:
    token = world.issuer.token(roles, merchant_id=uuid4() if "merchant" in roles else None)
    response = await call(world, method, path, make_settings(), headers=bearer(token), json={})
    assert response.status_code == expected


async def test_guest_checkout_is_allowed_by_default_and_can_be_closed(world: World) -> None:
    body = {"customer_id": str(uuid4())}
    open_ = await call(world, "POST", "/api/orders", make_settings(), json=body)
    closed = await call(
        world, "POST", "/api/orders", make_settings(allow_guest_checkout=False), json=body
    )
    assert open_.status_code == 200
    assert closed.status_code == 401
    assert "x-user-id" not in world.upstream("ordering")[0].headers


async def test_notifications_are_scoped_to_the_caller(world: World) -> None:
    me = uuid4()
    token = world.issuer.token(("customer",), user_id=me)
    other = await call(
        world,
        "GET",
        f"/api/notifications?customer_id={uuid4()}",
        make_settings(),
        headers=bearer(token),
    )
    assert other.status_code == 403
    mine = await call(
        world, "GET", "/api/notifications?page=2", make_settings(), headers=bearer(token)
    )
    assert mine.status_code == 200
    forwarded = world.upstream("notifications")[0]
    assert dict(forwarded.url.params)["customer_id"] == str(me)
    assert dict(forwarded.url.params)["page"] == "2"


async def test_admin_may_list_notifications_of_anyone(world: World) -> None:
    target = uuid4()
    token = world.issuer.token(("admin",))
    response = await call(
        world,
        "GET",
        f"/api/notifications?customer_id={target}",
        make_settings(),
        headers=bearer(token),
    )
    assert response.status_code == 200
    assert dict(world.upstream("notifications")[0].url.params)["customer_id"] == str(target)


async def test_payment_lookup_is_guarded_by_order_access(world: World) -> None:
    order = uuid4()
    token = world.issuer.token(("customer",))
    world.order_status = 404
    denied = await call(
        world, "GET", f"/api/payments/by-order/{order}", make_settings(), headers=bearer(token)
    )
    assert denied.status_code == 404
    assert world.upstream("payments") == []
    world.order_status = 200
    allowed = await call(
        world, "GET", f"/api/payments/by-order/{order}", make_settings(), headers=bearer(token)
    )
    assert allowed.status_code == 200
    check = world.upstream("ordering")[-1]
    assert check.url.path == f"/orders/{order}"
    assert "x-auth-sig" in check.headers


async def test_unavailable_jwks_fails_closed_for_tokens_but_not_for_anonymous(
    world: World,
) -> None:
    world.jwks_down = True
    token = world.issuer.token()
    authed = await call(world, "GET", "/api/orders/abc", make_settings(), headers=bearer(token))
    anonymous = await call(world, "GET", "/api/orders/abc", make_settings())
    assert authed.status_code == 503
    assert anonymous.status_code == 200


async def test_key_rotation_is_picked_up_through_an_unknown_kid(world: World) -> None:
    app = create_app(make_settings(), transport=httpx.MockTransport(world))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as client:
            first = await client.get("/api/orders/abc", headers=bearer(world.issuer.token()))
            rotated = Issuer("key-2")
            world.extra_keys.append(rotated.jwk())
            app.state.auth._verifier._jwks._min_refresh = 0.0
            second = await client.get("/api/orders/abc", headers=bearer(rotated.token()))
    assert first.status_code == second.status_code == 200
    assert world.jwks_hits == 2


async def test_jwks_refresh_is_throttled_against_unknown_kid_floods(world: World) -> None:
    app = create_app(make_settings(), transport=httpx.MockTransport(world))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as client:
            for index in range(20):
                response = await client.get(
                    "/api/orders/abc", headers=bearer(Issuer(f"rogue-{index}").token())
                )
                assert response.status_code == 401
    assert world.jwks_hits == 1


async def test_gateway_refuses_to_start_auth_without_a_secret() -> None:
    app = create_app(make_settings(internal_auth_secret=""))
    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            pass


async def test_stock_reads_forward_the_identity_when_the_token_is_valid(world: World) -> None:
    merchant = uuid4()
    token = world.issuer.token(("merchant",), merchant_id=merchant)
    response = await call(
        world, "GET", "/api/inventory/stock/abc", make_settings(), headers=bearer(token)
    )
    assert response.status_code == 200
    forwarded = world.upstream("inventory")[0]
    principal = verify_principal(SECRET, dict(forwarded.headers), forwarded.headers["x-request-id"])
    assert principal is not None and principal.merchant_id == merchant


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic abc"}]
)
async def test_stock_reads_stay_public_for_anonymous_or_broken_credentials(
    world: World, headers: dict[str, str]
) -> None:
    response = await call(world, "GET", "/api/inventory/stock", make_settings(), headers=headers)
    assert response.status_code == 200
    forwarded = world.upstream("inventory")[0]
    assert "x-user-id" not in forwarded.headers
    assert "authorization" not in forwarded.headers
