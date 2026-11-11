from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Role(StrEnum):
    CUSTOMER = "customer"
    MERCHANT = "merchant"
    ADMIN = "admin"


class Scope(StrEnum):
    ORDERS_CREATE = "orders:create"
    ORDERS_READ_OWN = "orders:read:own"
    ORDERS_READ_MERCHANT = "orders:read:merchant"
    ORDERS_READ_ANY = "orders:read:any"
    NOTIFICATIONS_READ_OWN = "notifications:read:own"
    STOCK_WRITE_OWN = "stock:write:own"
    STOCK_WRITE_ANY = "stock:write:any"
    LEDGER_READ_OWN = "ledger:read:own"
    LEDGER_READ_ANY = "ledger:read:any"
    LEDGER_RECONCILE = "ledger:reconcile"
    USERS_MANAGE = "users:manage"
    ASSISTANT_ADMIN = "assistant:admin"


_CUSTOMER_SCOPES = frozenset(
    {Scope.ORDERS_CREATE, Scope.ORDERS_READ_OWN, Scope.NOTIFICATIONS_READ_OWN}
)

ROLE_SCOPES: dict[Role, frozenset[Scope]] = {
    Role.CUSTOMER: _CUSTOMER_SCOPES,
    Role.MERCHANT: _CUSTOMER_SCOPES
    | {Scope.ORDERS_READ_MERCHANT, Scope.STOCK_WRITE_OWN, Scope.LEDGER_READ_OWN},
    Role.ADMIN: _CUSTOMER_SCOPES
    | {
        Scope.ORDERS_READ_ANY,
        Scope.ORDERS_READ_MERCHANT,
        Scope.STOCK_WRITE_ANY,
        Scope.LEDGER_READ_ANY,
        Scope.LEDGER_RECONCILE,
        Scope.USERS_MANAGE,
        Scope.ASSISTANT_ADMIN,
    },
}


def scopes_for_roles(roles: frozenset[str]) -> frozenset[str]:
    granted: set[str] = set()
    for role in roles:
        try:
            granted.update(scope.value for scope in ROLE_SCOPES[Role(role)])
        except ValueError:
            continue
    return frozenset(granted)


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    roles: frozenset[str]
    scopes: frozenset[str]
    merchant_id: UUID | None = None

    def has_role(self, role: Role) -> bool:
        return role.value in self.roles

    def can(self, scope: Scope) -> bool:
        return scope.value in self.scopes

    @property
    def is_admin(self) -> bool:
        return self.has_role(Role.ADMIN)

    def owns_merchant(self, merchant_id: UUID) -> bool:
        return self.merchant_id is not None and self.merchant_id == merchant_id
