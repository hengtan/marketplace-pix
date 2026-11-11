from datetime import UTC, datetime, timedelta
from uuid import uuid4

from marketplace_common.maintenance import CleanupJob, CleanupTarget, RetentionPolicy
from sqlalchemy import func, select

from identity.infrastructure.db.models import RefreshTokenModel


def token(expires_in: timedelta, used: bool = False) -> RefreshTokenModel:
    now = datetime.now(UTC)
    return RefreshTokenModel(
        id=uuid4(),
        family_id=uuid4(),
        user_id=uuid4(),
        token_hash=uuid4().hex + uuid4().hex,
        issued_at=now - timedelta(days=40),
        expires_at=now + expires_in,
        family_expires_at=now + timedelta(days=30),
        used_at=now if used else None,
    )


async def test_only_tokens_expired_beyond_the_retention_are_removed(engine, session_factory):
    async with session_factory() as session:
        session.add_all(
            [
                token(-timedelta(days=30)),
                token(-timedelta(days=30), used=True),
                token(-timedelta(days=1)),
                token(timedelta(days=3), used=True),
                token(timedelta(days=10)),
            ]
        )
        await session.commit()
    target = CleanupTarget(
        "refresh_tokens", "refresh_tokens", "expires_at", timedelta(days=7).total_seconds()
    )

    deleted = await CleanupJob(engine, [target], RetentionPolicy(pause_seconds=0.0)).run_once()

    assert deleted == {"refresh_tokens": 2}
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RefreshTokenModel)) == 3
