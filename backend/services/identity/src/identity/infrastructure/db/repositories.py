from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from identity.domain.tokens import RefreshTokenRecord
from identity.domain.user import User
from identity.infrastructure.db.models import RefreshTokenModel, UserModel


def _user_to_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        email=model.email,
        name=model.name,
        password_hash=model.password_hash,
        roles=frozenset(model.roles),
        merchant_id=model.merchant_id,
        disabled=model.disabled,
        failed_logins=model.failed_logins,
        locked_until=model.locked_until,
        created_at=model.created_at,
    )


def _token_to_domain(model: RefreshTokenModel) -> RefreshTokenRecord:
    return RefreshTokenRecord(
        id=model.id,
        family_id=model.family_id,
        user_id=model.user_id,
        token_hash=model.token_hash,
        issued_at=model.issued_at,
        expires_at=model.expires_at,
        family_expires_at=model.family_expires_at,
        used_at=model.used_at,
        revoked_at=model.revoked_at,
        access_jti=model.access_jti,
    )


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> bool:
        stmt = (
            insert(UserModel)
            .values(
                id=user.id,
                email=user.email,
                name=user.name,
                password_hash=user.password_hash,
                roles=sorted(user.roles),
                merchant_id=user.merchant_id,
                disabled=user.disabled,
            )
            .on_conflict_do_nothing(index_elements=["email"])
            .returning(UserModel.id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def get_by_email(self, email: str, lock: bool = False) -> User | None:
        stmt = select(UserModel).where(UserModel.email == email)
        if lock:
            stmt = stmt.with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if model is None else _user_to_domain(model)

    async def get_by_id(self, user_id: UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return None if model is None else _user_to_domain(model)

    async def save(self, user: User) -> None:
        model = await self._session.get(UserModel, user.id)
        if model is None:
            raise LookupError(f"user {user.id} not found")
        model.password_hash = user.password_hash
        model.disabled = user.disabled
        model.failed_logins = user.failed_logins
        model.locked_until = user.locked_until


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: RefreshTokenRecord) -> None:
        self._session.add(
            RefreshTokenModel(
                id=record.id,
                family_id=record.family_id,
                user_id=record.user_id,
                token_hash=record.token_hash,
                issued_at=record.issued_at,
                expires_at=record.expires_at,
                family_expires_at=record.family_expires_at,
                access_jti=record.access_jti,
            )
        )

    async def get_by_hash(self, token_hash: str, lock: bool = False) -> RefreshTokenRecord | None:
        stmt = select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        if lock:
            stmt = stmt.with_for_update()
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if model is None else _token_to_domain(model)

    async def mark_used(self, record_id: UUID, at: datetime) -> None:
        await self._session.execute(
            update(RefreshTokenModel).where(RefreshTokenModel.id == record_id).values(used_at=at)
        )

    async def access_tokens_since(
        self, family_id: UUID, since: datetime
    ) -> list[tuple[str, datetime]]:
        rows = await self._session.execute(
            select(RefreshTokenModel.access_jti, RefreshTokenModel.issued_at)
            .where(RefreshTokenModel.family_id == family_id)
            .where(RefreshTokenModel.access_jti.is_not(None))
            .where(RefreshTokenModel.issued_at > since)
        )
        return [(jti, issued_at) for jti, issued_at in rows.all() if jti is not None]

    async def revoke_family(self, family_id: UUID, at: datetime) -> int:
        result = await self._session.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.family_id == family_id)
            .where(RefreshTokenModel.revoked_at.is_(None))
            .values(revoked_at=at)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    async def revoke_user(self, user_id: UUID, at: datetime) -> int:
        result = await self._session.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.user_id == user_id)
            .where(RefreshTokenModel.revoked_at.is_(None))
            .values(revoked_at=at)
        )
        return int(result.rowcount)  # type: ignore[attr-defined]
