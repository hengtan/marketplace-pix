from __future__ import annotations

from uuid import UUID, uuid4

from marketplace_common.security import Principal, scopes_for_roles, sign_principal

SECRET = "test-internal-secret"


def as_user(
    roles: tuple[str, ...] = ("customer",),
    user_id: UUID | None = None,
    merchant_id: UUID | None = None,
    secret: str = SECRET,
) -> dict[str, str]:
    principal = Principal(
        user_id or uuid4(), frozenset(roles), scopes_for_roles(frozenset(roles)), merchant_id
    )
    return {**sign_principal(secret, principal, "req-test"), "x-request-id": "req-test"}
