from __future__ import annotations

from tests.test_gateway import Recorder, settings
from tests.test_resilience import Client


def limited() -> dict[str, object]:
    return {"rate_limit_per_minute": 3, "rate_limit_routes": {}}


async def hit(client, forwarded: str | None = None, extra: dict[str, str] | None = None) -> int:  # type: ignore[no-untyped-def]
    headers = dict(extra or {})
    if forwarded is not None:
        headers["X-Forwarded-For"] = forwarded
    return (await client.get("/api/catalog/products", headers=headers)).status_code


async def test_a_client_cannot_dodge_the_limit_by_forging_forwarded_for() -> None:
    async with Client(Recorder(), settings(**limited())) as client:
        codes = [await hit(client, f"198.51.100.{n}") for n in range(1, 7)]
    assert codes == [200, 200, 200, 429, 429, 429]


async def test_real_ip_header_is_ignored_without_a_trusted_proxy() -> None:
    async with Client(Recorder(), settings(**limited())) as client:
        codes = [await hit(client, extra={"X-Real-IP": f"198.51.100.{n}"}) for n in range(1, 6)]
    assert codes[-1] == 429


async def test_a_trusted_proxy_gives_each_real_client_its_own_bucket() -> None:
    cfg = settings(trusted_proxies=["127.0.0.0/8"], **limited())
    async with Client(Recorder(), cfg) as client:
        first = [await hit(client, "198.51.100.1") for _ in range(4)]
        second = [await hit(client, "198.51.100.2") for _ in range(3)]
    assert first == [200, 200, 200, 429]
    assert second == [200, 200, 200]


async def test_through_a_trusted_proxy_the_forged_left_part_does_not_matter() -> None:
    cfg = settings(trusted_proxies=["127.0.0.0/8"], **limited())
    async with Client(Recorder(), cfg) as client:
        codes = [await hit(client, f"6.6.6.{n}, 198.51.100.1") for n in range(1, 6)]
    assert codes == [200, 200, 200, 429, 429]


async def test_upstreams_receive_the_resolved_address_and_never_the_forged_one() -> None:
    recorder = Recorder()
    cfg = settings(trusted_proxies=["127.0.0.0/8"])
    async with Client(recorder, cfg) as client:
        await hit(client, "6.6.6.6, 198.51.100.1", {"X-Real-IP": "9.9.9.9"})
    forwarded = recorder.requests[0].headers
    assert forwarded["x-forwarded-for"] == "198.51.100.1"
    assert "x-real-ip" not in forwarded

    recorder = Recorder()
    async with Client(recorder, settings()) as client:
        await hit(client, "6.6.6.6", {"X-Real-IP": "9.9.9.9"})
    assert recorder.requests[0].headers["x-forwarded-for"] == "127.0.0.1"


def test_settings_accept_a_comma_separated_list() -> None:
    assert settings(trusted_proxies="10.0.0.0/8, 172.16.0.0/12").trusted_proxies == [
        "10.0.0.0/8",
        "172.16.0.0/12",
    ]
    assert settings().trusted_proxies == []
