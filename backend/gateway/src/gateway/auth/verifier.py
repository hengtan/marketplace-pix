from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt
from marketplace_common.security import Principal

from gateway.auth.jwks import JwksCache


class InvalidToken(Exception):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    principal: Principal
    jti: str


class TokenVerifier:
    def __init__(
        self, jwks: JwksCache, issuer: str, audience: str, leeway_seconds: int = 5
    ) -> None:
        self._jwks = jwks
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway_seconds

    async def verify(self, token: str) -> Principal:
        return (await self.verify_token(token)).principal

    async def verify_token(self, token: str) -> VerifiedToken:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise InvalidToken from error
        kid = header.get("kid")
        if header.get("alg") != "EdDSA" or not isinstance(kid, str):
            raise InvalidToken
        key = await self._jwks.get(kid)
        if key is None:
            raise InvalidToken
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["EdDSA"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub", "iss", "aud", "jti"]},
            )
            return VerifiedToken(
                Principal(
                    user_id=UUID(claims["sub"]),
                    roles=frozenset(claims.get("roles", [])),
                    scopes=frozenset(str(claims.get("scope", "")).split()),
                    merchant_id=UUID(claims["merchant_id"]) if claims.get("merchant_id") else None,
                ),
                str(claims["jti"]),
            )
        except (jwt.PyJWTError, ValueError, TypeError, KeyError) as error:
            raise InvalidToken from error
