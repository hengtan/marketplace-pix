from __future__ import annotations

import httpx
import pytest
from marketplace_common.resilience import InMemoryTokenBucket, RouteRateLimiter
from marketplace_common.security import ClientIpResolver
from marketplace_common.security.backoff import ProgressiveBackoff

from identity.application.abuse import AbuseGuard, AbusePolicy
from identity.application.auth import AuthPolicy, AuthService
from identity.interface.api import create_app
from tests.fakes import FakeHasher, FakeIssuer, FakeStore, FakeUow, MutableClock

PASSWORD = "correct horse battery"


class Ticker:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def build_guard(ticker: Ticker, **policy: object) -> AbuseGuard:
    abuse = AbusePolicy(**policy)  # type: ignore[arg-type]
    limiter = RouteRateLimiter(
        abuse.default_policy(),
        abuse.route_policies(),
        fallback=InMemoryTokenBucket(ticker),
    )
    backoff = ProgressiveBackoff(
        None,
        base_seconds=abuse.backoff_base_seconds,
        max_seconds=abuse.backoff_max_seconds,
        clock=ticker,
    )
    return AbuseGuard(limiter, backoff)


async def make_client(
    guard: AbuseGuard,
    *,
    peer: str = "203.0.113.9",
    trusted: list[str] | None = None,
    store: FakeStore | None = None,
) -> httpx.AsyncClient:
    store = store or FakeStore()
    auth = AuthService(
        lambda: FakeUow(store),
        FakeHasher(),
        FakeIssuer(),
        AuthPolicy(max_failed_logins=1000),
        MutableClock(),
    )
    app = create_app(
        auth=auth,
        jwks={"keys": []},
        abuse_guard=guard,
        client_ips=ClientIpResolver(trusted or []),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 5000)), base_url="http://t"
    )


async def register(client: httpx.AsyncClient, email: str, **headers: str) -> httpx.Response:
    return await client.post(
        "/auth/register",
        json={"email": email, "name": "Ana", "password": PASSWORD},
        headers=headers,
    )


async def login(client: httpx.AsyncClient, email: str, password: str, **headers: str):  # type: ignore[no-untyped-def]
    return await client.post(
        "/auth/login", json={"email": email, "password": password}, headers=headers
    )


async def test_repeated_logins_for_one_ip_and_email_are_limited() -> None:
    client = await make_client(build_guard(Ticker(), login_per_minute_ip_email=3))
    await register(client, "ana@example.com")
    codes = [(await login(client, "ana@example.com", PASSWORD)).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    blocked = await login(client, "ana@example.com", PASSWORD)
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.json()["detail"] == "too many attempts"
    assert blocked.json()["retry_after_seconds"] >= 1
    assert blocked.headers["cache-control"] == "no-store"


async def test_the_email_is_case_insensitive_and_other_emails_are_not_affected() -> None:
    client = await make_client(build_guard(Ticker(), login_per_minute_ip_email=2))
    for email in ("a@example.com", "A@Example.com"):
        await login(client, email, PASSWORD)
    assert (await login(client, " a@EXAMPLE.com", PASSWORD)).status_code == 429
    assert (await login(client, "b@example.com", PASSWORD)).status_code != 429


async def test_changing_the_email_does_not_dodge_the_per_ip_limit() -> None:
    client = await make_client(
        build_guard(Ticker(), login_per_minute_ip_email=100, login_per_minute_ip=4)
    )
    codes = [(await login(client, f"user{n}@example.com", PASSWORD)).status_code for n in range(6)]
    assert codes[:4] == [401] * 4 and codes[4:] == [429, 429]


async def test_mass_signup_from_one_ip_is_stopped() -> None:
    client = await make_client(build_guard(Ticker(), register_per_hour_ip=3))
    codes = [(await register(client, f"user{n}@example.com")).status_code for n in range(5)]
    assert codes == [201, 201, 201, 429, 429]


async def test_the_same_email_cannot_be_hammered_by_the_register_endpoint() -> None:
    client = await make_client(build_guard(Ticker(), register_per_hour_ip_email=2))
    codes = [(await register(client, "same@example.com")).status_code for _ in range(4)]
    assert codes == [201, 409, 429, 429]


async def test_failed_logins_back_off_progressively_and_success_resets() -> None:
    ticker = Ticker()
    client = await make_client(
        build_guard(ticker, backoff_base_seconds=2.0, backoff_max_seconds=60.0)
    )
    await register(client, "ana@example.com")
    first = await login(client, "ana@example.com", "wrong password")
    assert first.status_code == 401
    blocked = await login(client, "ana@example.com", PASSWORD)
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "2"

    ticker.now += 2.1
    assert (await login(client, "ana@example.com", "wrong password")).status_code == 401
    blocked = await login(client, "ana@example.com", PASSWORD)
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "4"

    ticker.now += 4.1
    assert (await login(client, "ana@example.com", PASSWORD)).status_code == 200
    again = await login(client, "ana@example.com", "wrong password")
    assert again.status_code == 401
    assert (await login(client, "ana@example.com", PASSWORD)).headers["retry-after"] == "2"


async def test_the_backoff_does_not_touch_other_accounts_or_other_clients() -> None:
    guard = build_guard(Ticker())
    shared = FakeStore()
    victim = await make_client(guard, peer="198.51.100.1", store=shared)
    other_ip = await make_client(guard, peer="198.51.100.2", store=shared)
    await register(victim, "ana@example.com")
    await login(victim, "ana@example.com", "wrong password")
    assert (await login(victim, "ana@example.com", PASSWORD)).status_code == 429
    assert (await login(other_ip, "ana@example.com", PASSWORD)).status_code == 200
    assert (await login(victim, "bia@example.com", PASSWORD)).status_code == 401


async def test_a_forged_forwarded_for_from_an_untrusted_peer_does_not_dodge_the_limit() -> None:
    client = await make_client(build_guard(Ticker(), login_per_minute_ip=3))
    codes = []
    for n in range(6):
        response = await login(
            client, f"u{n}@example.com", PASSWORD, **{"X-Forwarded-For": f"198.51.100.{n}"}
        )
        codes.append(response.status_code)
    assert codes[3:] == [429, 429, 429]


async def test_behind_a_trusted_proxy_each_real_client_has_its_own_budget() -> None:
    client = await make_client(
        build_guard(Ticker(), login_per_minute_ip=2), peer="10.0.0.5", trusted=["10.0.0.0/8"]
    )
    first = [
        (
            await login(
                client, f"a{n}@example.com", PASSWORD, **{"X-Forwarded-For": "198.51.100.1"}
            )
        ).status_code
        for n in range(3)
    ]
    second = (
        await login(client, "b@example.com", PASSWORD, **{"X-Forwarded-For": "198.51.100.2"})
    ).status_code
    assert first == [401, 401, 429] and second == 401


async def test_the_limiter_keys_never_contain_the_plain_email() -> None:
    guard = build_guard(Ticker())
    keys = guard.keys_for("login", "198.51.100.1", "Ana@Example.com")
    assert all("ana" not in key.lower() for key in keys)
    assert all("198.51.100.1" in key for key in keys)


@pytest.mark.parametrize("path", ["/auth/refresh", "/auth/logout"])
async def test_other_endpoints_are_not_throttled_by_the_guard(path: str) -> None:
    client = await make_client(build_guard(Ticker(), login_per_minute_ip=1, register_per_hour_ip=1))
    for _ in range(3):
        response = await client.post(path, json={"refresh_token": "x"})
        assert response.status_code != 429
