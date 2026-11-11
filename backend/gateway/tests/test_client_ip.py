from __future__ import annotations

import pytest

from gateway.client_ip import ClientIpResolver
from tests.test_gateway import Recorder, settings
from tests.test_resilience import Client

PROXY = "10.0.0.5"


def resolver(*networks: str) -> ClientIpResolver:
    return ClientIpResolver(list(networks))


@pytest.mark.parametrize(
    ("peer", "forwarded", "real", "expected"),
    [
        ("203.0.113.9", "1.2.3.4", None, "203.0.113.9"),
        ("203.0.113.9", None, "1.2.3.4", "203.0.113.9"),
        (PROXY, "198.51.100.7", None, "198.51.100.7"),
        (PROXY, "1.1.1.1, 198.51.100.7", None, "198.51.100.7"),
        (PROXY, "198.51.100.7, 10.0.0.9", None, "198.51.100.7"),
        (PROXY, None, "198.51.100.7", "198.51.100.7"),
        (PROXY, None, None, PROXY),
        (PROXY, "10.0.0.8, 10.0.0.9", None, "10.0.0.8"),
        (PROXY, "not-an-ip", None, PROXY),
        (PROXY, "198.51.100.7, garbage", None, PROXY),
        (PROXY, "2001:db8::1", None, "2001:db8::1"),
        (None, "1.2.3.4", None, "unknown"),
        ("garbage", "1.2.3.4", None, "garbage"),
    ],
)
def test_resolution_rules(peer: str | None, forwarded: str | None, real: str | None, expected: str):
    assert resolver("10.0.0.0/8").resolve(peer, forwarded, real) == expected


def test_no_trusted_proxies_means_the_header_is_never_read() -> None:
    assert resolver().resolve(PROXY, "1.2.3.4", "5.6.7.8") == PROXY


def test_cidr_and_single_addresses_are_accepted_and_bad_entries_rejected() -> None:
    assert resolver("192.168.1.1").resolve("192.168.1.1", "8.8.8.8", None) == "8.8.8.8"
    assert resolver("fd00::/8").resolve("fd00::5", "8.8.8.8", None) == "8.8.8.8"
    with pytest.raises(ValueError):
        resolver("not-a-network")


def test_settings_accept_a_comma_separated_list() -> None:
    assert settings(trusted_proxies="10.0.0.0/8, 172.16.0.0/12").trusted_proxies == [
        "10.0.0.0/8",
        "172.16.0.0/12",
    ]
    assert settings().trusted_proxies == []


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
