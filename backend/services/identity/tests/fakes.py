from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID

from identity.application.ports import IssuedAccessToken
from identity.domain.tokens import RefreshTokenRecord
from identity.domain.user import User


@dataclass
class FakeStore:
    users: dict[UUID, User] = field(default_factory=dict)
    tokens: dict[UUID, RefreshTokenRecord] = field(default_factory=dict)


class FakeUsers:
    def __init__(self, store: FakeStore) -> None:
        self._store = store

    async def add(self, user: User) -> bool:
        if any(u.email == user.email for u in self._store.users.values()):
            return False
        self._store.users[user.id] = user
        return True

    async def get_by_email(self, email: str, lock: bool = False) -> User | None:
        return next((u for u in self._store.users.values() if u.email == email), None)

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self._store.users.get(user_id)

    async def save(self, user: User) -> None:
        self._store.users[user.id] = user


class FakeTokens:
    def __init__(self, store: FakeStore) -> None:
        self._store = store

    async def add(self, record: RefreshTokenRecord) -> None:
        self._store.tokens[record.id] = record

    async def get_by_hash(self, token_hash: str, lock: bool = False) -> RefreshTokenRecord | None:
        return next((t for t in self._store.tokens.values() if t.token_hash == token_hash), None)

    async def mark_used(self, record_id: UUID, at: datetime) -> None:
        self._store.tokens[record_id] = replace(self._store.tokens[record_id], used_at=at)

    async def access_tokens_since(
        self, family_id: UUID, since: datetime
    ) -> list[tuple[str, datetime]]:
        return [
            (t.access_jti, t.issued_at)
            for t in self._store.tokens.values()
            if t.family_id == family_id and t.access_jti is not None and t.issued_at > since
        ]

    async def revoke_family(self, family_id: UUID, at: datetime) -> int:
        count = 0
        for key, token in list(self._store.tokens.items()):
            if token.family_id == family_id and token.revoked_at is None:
                self._store.tokens[key] = replace(token, revoked_at=at)
                count += 1
        return count

    async def revoke_user(self, user_id: UUID, at: datetime) -> int:
        count = 0
        for key, token in list(self._store.tokens.items()):
            if token.user_id == user_id and token.revoked_at is None:
                self._store.tokens[key] = replace(token, revoked_at=at)
                count += 1
        return count


class FakeUow:
    def __init__(self, committed: FakeStore) -> None:
        self._committed = committed
        self._working = copy.deepcopy(committed)
        self.users = FakeUsers(self._working)
        self.refresh_tokens = FakeTokens(self._working)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self._committed.users = self._working.users
        self._committed.tokens = self._working.tokens


class FakeHasher:
    def __init__(self) -> None:
        self.verifications = 0

    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        self.verifications += 1
        return password_hash == f"hashed:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return False


class FakeIssuer:
    def __init__(self) -> None:
        self.issued = 0

    def issue(self, user: User, session_id: UUID, now: datetime) -> IssuedAccessToken:
        self.issued += 1
        return IssuedAccessToken(
            f"access.{user.id}.{session_id}",
            600,
            f"jti-{self.issued}",
            now + timedelta(seconds=600),
        )


class FakeRevocations:
    def __init__(self) -> None:
        self.revoked: dict[str, float] = {}
        self.fail = False

    async def revoke(self, jti: str, ttl_seconds: float) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        self.revoked[jti] = ttl_seconds


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += timedelta(**kwargs)
