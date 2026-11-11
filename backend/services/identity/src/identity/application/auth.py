from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from marketplace_common.security import Role

from identity.application.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
    RefreshTokenReuse,
    UserNotFound,
)
from identity.application.ports import (
    AccessTokenIssuer,
    AccessTokenRevocations,
    PasswordHasher,
    UnitOfWork,
)
from identity.domain.errors import DomainError
from identity.domain.tokens import RefreshTokenRecord
from identity.domain.user import User, normalize_email, validate_password
from identity.metrics import ACCESS_REVOCATIONS, LOGINS, REFRESHES, REGISTRATIONS

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]
UowFactory = Callable[[], UnitOfWork]

DUMMY_PASSWORD = "dummy-password-for-timing-equalisation"
ACCESS_REVOCATION_LEEWAY_SECONDS = 10


def utcnow() -> datetime:
    return datetime.now(UTC)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class AuthPolicy:
    refresh_ttl: timedelta = timedelta(days=14)
    session_max: timedelta = timedelta(days=30)
    max_failed_logins: int = 5
    lockout: timedelta = timedelta(minutes=15)
    access_ttl: timedelta = timedelta(minutes=10)


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int
    user: User


class AuthService:
    def __init__(
        self,
        uow_factory: UowFactory,
        hasher: PasswordHasher,
        issuer: AccessTokenIssuer,
        policy: AuthPolicy | None = None,
        clock: Clock = utcnow,
        revocations: AccessTokenRevocations | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._issuer = issuer
        self._policy = policy or AuthPolicy()
        self._clock = clock
        self._revocations = revocations
        self._dummy_hash: str | None = None

    async def register_customer(self, email: str, name: str, password: str) -> TokenPair:
        user = await self._build_user(email, name, password, frozenset({Role.CUSTOMER.value}), None)
        async with self._uow_factory() as uow:
            if not await uow.users.add(user):
                raise EmailAlreadyRegistered(user.email)
            pair = await self._start_session(uow, user)
            await uow.commit()
        REGISTRATIONS.labels(role=Role.CUSTOMER.value).inc()
        return pair

    async def create_user(
        self,
        email: str,
        name: str,
        password: str,
        roles: frozenset[str],
        merchant_id: UUID | None = None,
    ) -> User:
        user = await self._build_user(email, name, password, roles, merchant_id)
        async with self._uow_factory() as uow:
            if not await uow.users.add(user):
                raise EmailAlreadyRegistered(user.email)
            await uow.commit()
        for role in roles:
            REGISTRATIONS.labels(role=role).inc()
        return user

    async def _build_user(
        self,
        email: str,
        name: str,
        password: str,
        roles: frozenset[str],
        merchant_id: UUID | None,
    ) -> User:
        normalized = normalize_email(email)
        validate_password(password, normalized)
        return User.create(normalized, name, await self._hasher.hash(password), roles, merchant_id)

    async def login(self, email: str, password: str) -> TokenPair:
        try:
            normalized = normalize_email(email)
        except DomainError:
            await self._burn_time(password)
            LOGINS.labels(result="invalid").inc()
            raise InvalidCredentials from None
        now = self._clock()
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_email(normalized, lock=True)
            if user is None or user.disabled or user.is_locked(now):
                await self._burn_time(password)
                LOGINS.labels(result="rejected").inc()
                raise InvalidCredentials
            if not await self._hasher.verify(user.password_hash, password):
                user.record_failure(now, self._policy.max_failed_logins, self._policy.lockout)
                await uow.users.save(user)
                await uow.commit()
                LOGINS.labels(result="invalid").inc()
                raise InvalidCredentials
            user.record_success()
            if self._hasher.needs_rehash(user.password_hash):
                user.password_hash = await self._hasher.hash(password)
            await uow.users.save(user)
            pair = await self._start_session(uow, user)
            await uow.commit()
        LOGINS.labels(result="success").inc()
        return pair

    async def refresh(self, refresh_token: str) -> TokenPair:
        now = self._clock()
        token_hash = hash_refresh_token(refresh_token)
        async with self._uow_factory() as uow:
            record = await uow.refresh_tokens.get_by_hash(token_hash, lock=True)
            if record is None:
                REFRESHES.labels(result="unknown").inc()
                raise InvalidRefreshToken
            if record.revoked_at is not None or record.is_expired(now):
                REFRESHES.labels(result="expired").inc()
                raise InvalidRefreshToken
            if record.used_at is not None:
                await uow.refresh_tokens.revoke_family(record.family_id, now)
                jtis = await self._live_access_tokens(uow, record.family_id, now)
                await uow.commit()
                await self._revoke_access_tokens(jtis, now)
                REFRESHES.labels(result="reuse").inc()
                logger.warning(
                    "refresh token reuse detected, session family revoked",
                    extra={"user_id": str(record.user_id), "family_id": str(record.family_id)},
                )
                raise RefreshTokenReuse
            user = await uow.users.get_by_id(record.user_id)
            if user is None or user.disabled:
                await uow.refresh_tokens.revoke_family(record.family_id, now)
                jtis = await self._live_access_tokens(uow, record.family_id, now)
                await uow.commit()
                await self._revoke_access_tokens(jtis, now)
                REFRESHES.labels(result="disabled").inc()
                raise InvalidRefreshToken
            await uow.refresh_tokens.mark_used(record.id, now)
            pair = await self._rotate(uow, user, record, now)
            await uow.commit()
        REFRESHES.labels(result="success").inc()
        return pair

    async def logout(self, refresh_token: str) -> None:
        now = self._clock()
        async with self._uow_factory() as uow:
            record = await uow.refresh_tokens.get_by_hash(
                hash_refresh_token(refresh_token), lock=True
            )
            if record is not None:
                await uow.refresh_tokens.revoke_family(record.family_id, now)
                jtis = await self._live_access_tokens(uow, record.family_id, now)
                await uow.commit()
                await self._revoke_access_tokens(jtis, now)

    async def _live_access_tokens(
        self, uow: UnitOfWork, family_id: UUID, now: datetime
    ) -> list[tuple[str, datetime]]:
        issued = await uow.refresh_tokens.access_tokens_since(
            family_id, now - self._policy.access_ttl
        )
        return [(jti, issued_at + self._policy.access_ttl) for jti, issued_at in issued]

    async def _revoke_access_tokens(
        self, tokens: list[tuple[str, datetime]], now: datetime
    ) -> None:
        if self._revocations is None:
            return
        for jti, expires_at in tokens:
            ttl = (expires_at - now).total_seconds() + ACCESS_REVOCATION_LEEWAY_SECONDS
            try:
                await self._revocations.revoke(jti, ttl)
            except Exception:
                ACCESS_REVOCATIONS.labels(result="error").inc()
                logger.exception("could not revoke an access token", extra={"jti": jti})
            else:
                ACCESS_REVOCATIONS.labels(result="revoked").inc()

    async def get_user(self, user_id: UUID) -> User:
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_id(user_id)
        if user is None:
            raise UserNotFound(str(user_id))
        return user

    async def _start_session(self, uow: UnitOfWork, user: User) -> TokenPair:
        now = self._clock()
        family_id = uuid4()
        return await self._issue(
            uow, user, family_id, now, family_expires_at=now + self._policy.session_max
        )

    async def _rotate(
        self, uow: UnitOfWork, user: User, previous: RefreshTokenRecord, now: datetime
    ) -> TokenPair:
        return await self._issue(
            uow, user, previous.family_id, now, family_expires_at=previous.family_expires_at
        )

    async def _issue(
        self,
        uow: UnitOfWork,
        user: User,
        family_id: UUID,
        now: datetime,
        family_expires_at: datetime,
    ) -> TokenPair:
        refresh_token = secrets.token_urlsafe(48)
        access = self._issuer.issue(user, family_id, now)
        await uow.refresh_tokens.add(
            RefreshTokenRecord(
                id=uuid4(),
                family_id=family_id,
                user_id=user.id,
                token_hash=hash_refresh_token(refresh_token),
                issued_at=now,
                expires_at=min(now + self._policy.refresh_ttl, family_expires_at),
                family_expires_at=family_expires_at,
                access_jti=access.jti,
            )
        )
        return TokenPair(access.token, refresh_token, access.expires_in, user)

    async def _burn_time(self, password: str) -> None:
        if self._dummy_hash is None:
            self._dummy_hash = await self._hasher.hash(DUMMY_PASSWORD)
        await self._hasher.verify(self._dummy_hash, password)
