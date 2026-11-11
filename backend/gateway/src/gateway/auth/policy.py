from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from marketplace_common.security import Scope


class Access(StrEnum):
    PUBLIC = "public"
    OPTIONAL = "optional"
    SOFT = "soft"
    REQUIRED = "required"


@dataclass(frozen=True, slots=True)
class Rule:
    methods: frozenset[str]
    pattern: re.Pattern[str]
    access: Access
    any_scope: tuple[Scope, ...] = ()
    own_customer_param: bool = False
    object_guard: bool = False


def _rule(
    methods: str,
    pattern: str,
    access: Access,
    *scopes: Scope,
    own_customer_param: bool = False,
    object_guard: bool = False,
) -> Rule:
    return Rule(
        frozenset(methods.split("|")),
        re.compile(pattern),
        access,
        tuple(scopes),
        own_customer_param,
        object_guard,
    )


READ = "GET|HEAD|OPTIONS"


def build_rules(guest_checkout: bool) -> tuple[Rule, ...]:
    checkout = Access.OPTIONAL if guest_checkout else Access.REQUIRED
    return (
        _rule("POST", r"^/api/auth/(register|login|refresh|logout)$", Access.PUBLIC),
        _rule("GET", r"^/api/auth/me$", Access.REQUIRED),
        _rule("POST", r"^/api/auth/admin/users$", Access.REQUIRED, Scope.USERS_MANAGE),
        _rule(READ, r"^/api/catalog(/.*)?$", Access.PUBLIC),
        _rule(
            "POST|PATCH|DELETE",
            r"^/api/catalog/products(/[^/]+)?$",
            Access.REQUIRED,
            Scope.CATALOG_WRITE_OWN,
            Scope.CATALOG_WRITE_ANY,
        ),
        _rule("GET", r"^/api/inventory/stock/mine$", Access.REQUIRED, Scope.STOCK_WRITE_OWN),
        _rule(READ, r"^/api/inventory/stock(/.*)?$", Access.SOFT),
        _rule(
            "PUT",
            r"^/api/inventory/stock/[^/]+$",
            Access.REQUIRED,
            Scope.STOCK_WRITE_OWN,
            Scope.STOCK_WRITE_ANY,
        ),
        _rule("POST", r"^/api/orders$", checkout),
        _rule(
            "GET",
            r"^/api/orders/merchant$",
            Access.REQUIRED,
            Scope.ORDERS_READ_MERCHANT,
        ),
        _rule("GET", r"^/api/orders(/[^/]+)?$", Access.OPTIONAL),
        _rule("GET", r"^/api/payments/by-order/[^/]+$", Access.OPTIONAL, object_guard=True),
        _rule("POST", r"^/api/payments/dev/.*$", Access.OPTIONAL),
        _rule(
            "GET",
            r"^/api/notifications$",
            Access.REQUIRED,
            Scope.NOTIFICATIONS_READ_OWN,
            own_customer_param=True,
        ),
        _rule(
            "GET",
            r"^/api/notifications/[^/]+/preview$",
            Access.REQUIRED,
            Scope.NOTIFICATIONS_READ_OWN,
        ),
        _rule("GET", r"^/api/ledger/reconciliation$", Access.REQUIRED, Scope.LEDGER_RECONCILE),
        _rule(
            "GET",
            r"^/api/ledger/.*$",
            Access.REQUIRED,
            Scope.LEDGER_READ_OWN,
            Scope.LEDGER_READ_ANY,
        ),
        _rule("POST", r"^/api/assistant/admin/.*$", Access.REQUIRED, Scope.ASSISTANT_ADMIN),
        _rule("GET|POST", r"^/api/assistant/.*$", Access.OPTIONAL),
    )


def match(rules: tuple[Rule, ...], method: str, path: str) -> Rule | None:
    for rule in rules:
        if method in rule.methods and rule.pattern.match(path):
            return rule
    return None
