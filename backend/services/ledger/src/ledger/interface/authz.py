from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from marketplace_common.security import Principal, Scope

MERCHANT_PREFIX = "merchant:"


def require_scope(principal: Principal | None, scope: Scope) -> Principal:
    if principal is None:
        raise HTTPException(401, "authentication required")
    if not principal.can(scope):
        raise HTTPException(403, "forbidden")
    return principal


def authorize_merchant(principal: Principal | None, merchant_id: UUID) -> Principal:
    if principal is None:
        raise HTTPException(401, "authentication required")
    if principal.can(Scope.LEDGER_READ_ANY):
        return principal
    if principal.can(Scope.LEDGER_READ_OWN) and principal.owns_merchant(merchant_id):
        return principal
    raise HTTPException(403, "forbidden")


def authorize_account(principal: Principal | None, account_id: str) -> Principal:
    if principal is None:
        raise HTTPException(401, "authentication required")
    if principal.can(Scope.LEDGER_READ_ANY):
        return principal
    if account_id.startswith(MERCHANT_PREFIX):
        try:
            owner = UUID(account_id.removeprefix(MERCHANT_PREFIX))
        except ValueError:
            raise HTTPException(403, "forbidden") from None
        return authorize_merchant(principal, owner)
    raise HTTPException(403, "forbidden")
