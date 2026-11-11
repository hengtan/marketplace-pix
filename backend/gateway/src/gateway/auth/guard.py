from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qsl, urlencode

import httpx
from fastapi import Request
from marketplace_common.security import Principal, sign_principal, strip_identity_headers
from marketplace_common.security.revocation import RevocationUnavailable

from gateway.auth.jwks import JwksUnavailable
from gateway.auth.policy import Access, build_rules, match
from gateway.auth.verifier import InvalidToken, TokenVerifier

logger = logging.getLogger(__name__)


class Revocations(Protocol):
    async def is_revoked(self, jti: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class Denied:
    status: int
    detail: str
    challenge: bool = False


@dataclass(frozen=True, slots=True)
class Allowed:
    principal: Principal | None
    query: str


class GatewayAuth:
    def __init__(
        self,
        verifier: TokenVerifier,
        internal_secret: str,
        guest_checkout: bool = True,
        ordering_url: str = "",
        revocations: Revocations | None = None,
    ) -> None:
        if not internal_secret:
            raise RuntimeError("INTERNAL_AUTH_SECRET is required when auth is enabled")
        self._verifier = verifier
        self._secret = internal_secret
        self._rules = build_rules(guest_checkout)
        self._ordering_url = ordering_url
        self._revocations = revocations

    async def authorize(
        self, request: Request, client: httpx.AsyncClient, request_id: str
    ) -> Allowed | Denied:
        rule = match(self._rules, request.method, request.url.path)
        access = rule.access if rule else Access.REQUIRED
        principal, failure = await self._authenticate(request, access)
        if failure is not None:
            return failure
        if rule is not None and rule.any_scope:
            if principal is None:
                return Denied(401, "authentication required", challenge=True)
            if not any(principal.can(scope) for scope in rule.any_scope):
                return Denied(403, "forbidden")
        if rule is None and principal is None:
            return Denied(401, "authentication required", challenge=True)
        query = request.url.query
        if rule is not None and rule.own_customer_param and principal is not None:
            outcome = self._scope_customer_query(query, principal)
            if isinstance(outcome, Denied):
                return outcome
            query = outcome
        if rule is not None and rule.object_guard:
            denied = await self._check_order_access(request, client, principal, request_id)
            if denied is not None:
                return denied
        return Allowed(principal, query)

    def upstream_headers(
        self, incoming: dict[str, str], principal: Principal | None, request_id: str
    ) -> dict[str, str]:
        headers = {
            k: v
            for k, v in strip_identity_headers(incoming).items()
            if k.lower() != "authorization"
        }
        if principal is not None:
            headers.update(sign_principal(self._secret, principal, request_id))
        return headers

    async def _authenticate(
        self, request: Request, access: Access
    ) -> tuple[Principal | None, Denied | None]:
        header = request.headers.get("authorization")
        if access is Access.PUBLIC:
            return None, None
        if header is None:
            if access in (Access.OPTIONAL, Access.SOFT):
                return None, None
            return None, Denied(401, "authentication required", challenge=True)
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            if access is Access.SOFT:
                return None, None
            return None, Denied(401, "invalid authorization header", challenge=True)
        try:
            verified = await self._verifier.verify_token(token.strip())
            if self._revocations is not None and await self._revocations.is_revoked(verified.jti):
                if access is Access.SOFT:
                    return None, None
                return None, Denied(401, "invalid or expired token", challenge=True)
            return verified.principal, None
        except InvalidToken:
            if access is Access.SOFT:
                return None, None
            return None, Denied(401, "invalid or expired token", challenge=True)
        except (JwksUnavailable, RevocationUnavailable):
            if access is Access.SOFT:
                return None, None
            logger.error("token validation unavailable, rejecting authenticated request")
            return None, Denied(503, "authentication unavailable")

    @staticmethod
    def _scope_customer_query(query: str, principal: Principal) -> str | Denied:
        if principal.is_admin:
            return query
        pairs = parse_qsl(query, keep_blank_values=True)
        asked = [v for k, v in pairs if k == "customer_id"]
        if any(value != str(principal.user_id) for value in asked):
            return Denied(403, "forbidden")
        rest = [(k, v) for k, v in pairs if k != "customer_id"]
        rest.append(("customer_id", str(principal.user_id)))
        return urlencode(rest)

    async def _check_order_access(
        self,
        request: Request,
        client: httpx.AsyncClient,
        principal: Principal | None,
        request_id: str,
    ) -> Denied | None:
        order_id = request.url.path.rsplit("/", 1)[-1]
        headers = {"x-request-id": request_id}
        if principal is not None:
            headers.update(sign_principal(self._secret, principal, request_id))
        try:
            response = await client.get(f"{self._ordering_url}/orders/{order_id}", headers=headers)
        except httpx.HTTPError:
            return Denied(502, "upstream unavailable")
        if response.status_code == 200:
            return None
        if response.status_code in (404, 422):
            return Denied(404, "not found")
        return Denied(response.status_code, "upstream error")
