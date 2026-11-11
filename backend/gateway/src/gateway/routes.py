from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Route:
    prefix: str
    service: str
    strip: str
    dev_only: bool = False


ROUTES: tuple[Route, ...] = (
    Route("/api/catalog", "catalog", "/api/catalog"),
    Route("/api/inventory", "inventory", "/api/inventory"),
    Route("/api/ledger", "ledger", "/api/ledger"),
    Route("/api/orders", "ordering", "/api"),
    Route("/api/payments/by-order", "payments", "/api"),
    Route("/api/payments/dev", "payments", "/api/payments", dev_only=True),
    Route("/api/notifications", "notifications", "/api"),
    Route("/api/assistant", "assistant", "/api/assistant"),
    Route("/api/auth", "identity", "/api"),
)


@dataclass(frozen=True, slots=True)
class Target:
    service: str
    path: str
    dev_only: bool


def resolve(path: str) -> Target | None:
    for route in ROUTES:
        if path == route.prefix or path.startswith(route.prefix + "/"):
            return Target(route.service, path[len(route.strip) :] or "/", route.dev_only)
    return None
