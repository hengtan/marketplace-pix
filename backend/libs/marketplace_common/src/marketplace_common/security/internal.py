from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from uuid import UUID

from fastapi import Request

from marketplace_common.security.principal import Principal

HEADER_USER_ID = "x-user-id"
HEADER_USER_ROLES = "x-user-roles"
HEADER_USER_SCOPES = "x-user-scopes"
HEADER_MERCHANT_ID = "x-merchant-id"
HEADER_AUTH_TS = "x-auth-ts"
HEADER_AUTH_SIG = "x-auth-sig"

IDENTITY_HEADERS = (
    HEADER_USER_ID,
    HEADER_USER_ROLES,
    HEADER_USER_SCOPES,
    HEADER_MERCHANT_ID,
    HEADER_AUTH_TS,
    HEADER_AUTH_SIG,
)

DEFAULT_MAX_SKEW_SECONDS = 60


def _canonical(
    user_id: str, roles: str, scopes: str, merchant_id: str, timestamp: str, request_id: str
) -> bytes:
    return "\n".join((user_id, roles, scopes, merchant_id, timestamp, request_id)).encode()


def _mac(secret: str, payload: bytes) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def strip_identity_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in IDENTITY_HEADERS}


def sign_principal(
    secret: str, principal: Principal, request_id: str, now: float | None = None
) -> dict[str, str]:
    timestamp = str(int(now if now is not None else time.time()))
    roles = ",".join(sorted(principal.roles))
    scopes = " ".join(sorted(principal.scopes))
    merchant = str(principal.merchant_id) if principal.merchant_id else ""
    signature = _mac(
        secret,
        _canonical(str(principal.user_id), roles, scopes, merchant, timestamp, request_id),
    )
    headers = {
        HEADER_USER_ID: str(principal.user_id),
        HEADER_USER_ROLES: roles,
        HEADER_USER_SCOPES: scopes,
        HEADER_AUTH_TS: timestamp,
        HEADER_AUTH_SIG: signature,
    }
    if merchant:
        headers[HEADER_MERCHANT_ID] = merchant
    return headers


def verify_principal(
    secret: str,
    headers: Mapping[str, str],
    request_id: str,
    now: float | None = None,
    max_skew: int = DEFAULT_MAX_SKEW_SECONDS,
) -> Principal | None:
    if not secret:
        return None
    lowered = {k.lower(): v for k, v in headers.items()}
    user_id = lowered.get(HEADER_USER_ID)
    timestamp = lowered.get(HEADER_AUTH_TS)
    signature = lowered.get(HEADER_AUTH_SIG)
    if not user_id or not timestamp or not signature:
        return None
    roles = lowered.get(HEADER_USER_ROLES, "")
    scopes = lowered.get(HEADER_USER_SCOPES, "")
    merchant = lowered.get(HEADER_MERCHANT_ID, "")
    expected = _mac(secret, _canonical(user_id, roles, scopes, merchant, timestamp, request_id))
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        issued = int(timestamp)
        if abs((now if now is not None else time.time()) - issued) > max_skew:
            return None
        return Principal(
            user_id=UUID(user_id),
            roles=frozenset(r for r in roles.split(",") if r),
            scopes=frozenset(s for s in scopes.split(" ") if s),
            merchant_id=UUID(merchant) if merchant else None,
        )
    except ValueError:
        return None


class PrincipalResolver:
    """Dependência FastAPI: só aceita identidade assinada pelo gateway, senão trata como anônimo."""

    def __init__(self, secret: str, max_skew: int = DEFAULT_MAX_SKEW_SECONDS) -> None:
        self._secret = secret
        self._max_skew = max_skew

    def __call__(self, request: Request) -> Principal | None:
        request_id = request.headers.get("x-request-id", "")
        return verify_principal(self._secret, request.headers, request_id, max_skew=self._max_skew)
