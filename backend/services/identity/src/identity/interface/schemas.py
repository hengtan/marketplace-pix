from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from identity.application.auth import TokenPair
from identity.domain.user import User

PASSWORD_FIELD = Field(min_length=1, max_length=128)


class RegisterIn(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str = PASSWORD_FIELD


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = PASSWORD_FIELD


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class AdminCreateUserIn(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str = PASSWORD_FIELD
    roles: list[str] = Field(min_length=1, max_length=3)
    merchant_id: UUID | None = None
    merchant_slug: str | None = Field(default=None, max_length=80)


class UserOut(BaseModel):
    id: UUID
    email: str
    name: str
    roles: list[str]
    merchant_id: UUID | None

    @classmethod
    def from_domain(cls, user: User) -> UserOut:
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            roles=sorted(user.roles),
            merchant_id=user.merchant_id,
        )


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserOut

    @classmethod
    def from_domain(cls, pair: TokenPair) -> TokensOut:
        return cls(
            access_token=pair.access_token,
            refresh_token=pair.refresh_token,
            expires_in=pair.expires_in,
            user=UserOut.from_domain(pair.user),
        )
