from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

import jwt
from marketplace_common.security import scopes_for_roles

from identity.application.ports import IssuedAccessToken
from identity.domain.user import User
from identity.infrastructure.security.keys import SigningKeys


class JwtAccessTokenIssuer:
    def __init__(
        self, keys: SigningKeys, issuer: str, audience: str, ttl: timedelta = timedelta(minutes=10)
    ) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience
        self._ttl = ttl

    def issue(self, user: User, session_id: UUID, now: datetime) -> IssuedAccessToken:
        claims: dict[str, object] = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(user.id),
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + self._ttl).timestamp()),
            "jti": uuid4().hex,
            "sid": str(session_id),
            "roles": sorted(user.roles),
            "scope": " ".join(sorted(scopes_for_roles(user.roles))),
        }
        if user.merchant_id is not None:
            claims["merchant_id"] = str(user.merchant_id)
        token = jwt.encode(
            claims,
            self._keys.private_key,
            algorithm="EdDSA",
            headers={"kid": self._keys.kid, "typ": "at+jwt"},
        )
        return IssuedAccessToken(token, int(self._ttl.total_seconds()))
