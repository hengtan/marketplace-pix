from __future__ import annotations

import pytest

from marketplace_common.security import ClientIpResolver

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
