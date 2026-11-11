from __future__ import annotations

from collections.abc import Sequence
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network

UNKNOWN = "unknown"

Network = IPv4Network | IPv6Network
Address = IPv4Address | IPv6Address


def _parse(value: str) -> Address | None:
    try:
        return ip_address(value.strip())
    except ValueError:
        return None


class ClientIpResolver:
    """Descobre o cliente real. `X-Forwarded-For` e `X-Real-IP` só valem quando quem conectou
    é um proxy confiável. A cadeia é lida da direita para a esquerda e o primeiro endereço que
    não é de um proxy confiável é o cliente: o que o cliente escreveu à esquerda nunca conta."""

    def __init__(self, trusted: Sequence[str]) -> None:
        self._trusted: tuple[Network, ...] = tuple(
            ip_network(n.strip()) for n in trusted if n.strip()
        )

    def _is_trusted(self, address: Address) -> bool:
        return any(address in network for network in self._trusted)

    def resolve(self, peer: str | None, forwarded_for: str | None, real_ip: str | None) -> str:
        if not peer:
            return UNKNOWN
        peer_address = _parse(peer)
        if peer_address is None or not self._is_trusted(peer_address):
            return peer
        if forwarded_for:
            return self._from_chain(peer, forwarded_for)
        if real_ip:
            parsed = _parse(real_ip)
            return str(parsed) if parsed is not None else peer
        return peer

    def _from_chain(self, peer: str, forwarded_for: str) -> str:
        hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
        for raw in reversed(hops):
            address = _parse(raw)
            if address is None:
                return peer
            if not self._is_trusted(address):
                return str(address)
        first = _parse(hops[0]) if hops else None
        return str(first) if first is not None else peer
