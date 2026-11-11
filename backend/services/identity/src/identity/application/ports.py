from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from identity.domain.tokens import RefreshTokenRecord
from identity.domain.user import User


@dataclass(frozen=True, slots=True)
class IssuedAccessToken:
    token: str
    expires_in: int
    jti: str
    expires_at: datetime


class PasswordHasher(Protocol):
    async def hash(self, password: str) -> str: ...

    async def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class AccessTokenIssuer(Protocol):
    def issue(self, user: User, session_id: UUID, now: datetime) -> IssuedAccessToken: ...


class AccessTokenRevocations(Protocol):
    async def revoke(self, jti: str, ttl_seconds: float) -> None: ...


class UserRepository(Protocol):
    async def add(self, user: User) -> bool: ...

    async def get_by_email(self, email: str, lock: bool = False) -> User | None: ...

    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def save(self, user: User) -> None: ...


class RefreshTokenRepository(Protocol):
    async def add(self, record: RefreshTokenRecord) -> None: ...

    async def get_by_hash(
        self, token_hash: str, lock: bool = False
    ) -> RefreshTokenRecord | None: ...

    async def mark_used(self, record_id: UUID, at: datetime) -> None: ...

    async def access_tokens_since(
        self, family_id: UUID, since: datetime
    ) -> list[tuple[str, datetime]]: ...

    async def revoke_family(self, family_id: UUID, at: datetime) -> int: ...

    async def revoke_user(self, user_id: UUID, at: datetime) -> int: ...


class UnitOfWork(Protocol):
    @property
    def users(self) -> UserRepository: ...

    @property
    def refresh_tokens(self) -> RefreshTokenRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...
