from __future__ import annotations

from datetime import timedelta

import pytest

from identity.application.auth import ACCESS_REVOCATION_LEEWAY_SECONDS, AuthPolicy, AuthService
from identity.application.errors import InvalidRefreshToken, RefreshTokenReuse
from tests.fakes import (
    FakeHasher,
    FakeIssuer,
    FakeRevocations,
    FakeStore,
    FakeUow,
    MutableClock,
)

PASSWORD = "correct horse battery"
ACCESS_TTL = 600
LEEWAY = ACCESS_REVOCATION_LEEWAY_SECONDS


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def revocations() -> FakeRevocations:
    return FakeRevocations()


@pytest.fixture
def auth(store: FakeStore, clock: MutableClock, revocations: FakeRevocations) -> AuthService:
    return AuthService(
        lambda: FakeUow(store),
        FakeHasher(),
        FakeIssuer(),
        AuthPolicy(access_ttl=timedelta(seconds=ACCESS_TTL)),
        clock,
        revocations,
    )


async def test_logout_revokes_the_access_token_for_its_remaining_life(
    auth: AuthService, clock: MutableClock, revocations: FakeRevocations
) -> None:
    await auth.register_customer("a@example.com", "Ana", PASSWORD)
    pair = await auth.login("a@example.com", PASSWORD)
    clock.now += timedelta(seconds=120)
    await auth.logout(pair.refresh_token)
    assert revocations.revoked == {"jti-2": ACCESS_TTL - 120 + LEEWAY}


async def test_logout_revokes_every_recent_access_token_of_the_session_only(
    auth: AuthService, clock: MutableClock, revocations: FakeRevocations
) -> None:
    await auth.register_customer("b@example.com", "Bia", PASSWORD)
    pair = await auth.register_customer("a@example.com", "Ana", PASSWORD)
    clock.now += timedelta(seconds=ACCESS_TTL + 60)
    rotated = await auth.refresh(pair.refresh_token)
    clock.now += timedelta(seconds=30)
    rotated = await auth.refresh(rotated.refresh_token)
    clock.now += timedelta(seconds=10)
    await auth.logout(rotated.refresh_token)
    assert set(revocations.revoked) == {"jti-3", "jti-4"}
    assert "jti-1" not in revocations.revoked


async def test_reuse_detection_revokes_the_access_tokens_of_the_family(
    auth: AuthService, clock: MutableClock, revocations: FakeRevocations
) -> None:
    pair = await auth.register_customer("a@example.com", "Ana", PASSWORD)
    clock.now += timedelta(seconds=30)
    rotated = await auth.refresh(pair.refresh_token)
    clock.now += timedelta(seconds=30)
    with pytest.raises(RefreshTokenReuse):
        await auth.refresh(pair.refresh_token)
    assert set(revocations.revoked) == {"jti-1", "jti-2"}
    assert revocations.revoked["jti-2"] == ACCESS_TTL - 30 + LEEWAY
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(rotated.refresh_token)


async def test_another_session_of_the_same_user_keeps_working(
    auth: AuthService, revocations: FakeRevocations
) -> None:
    await auth.register_customer("a@example.com", "Ana", PASSWORD)
    phone = await auth.login("a@example.com", PASSWORD)
    await auth.login("a@example.com", PASSWORD)
    await auth.logout(phone.refresh_token)
    assert set(revocations.revoked) == {"jti-2"}


async def test_a_failing_revocation_store_does_not_break_the_logout(
    auth: AuthService, revocations: FakeRevocations
) -> None:
    pair = await auth.register_customer("a@example.com", "Ana", PASSWORD)
    revocations.fail = True
    await auth.logout(pair.refresh_token)
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(pair.refresh_token)


async def test_logout_with_an_unknown_token_revokes_nothing(
    auth: AuthService, revocations: FakeRevocations
) -> None:
    await auth.logout("never-issued")
    assert revocations.revoked == {}


async def test_a_disabled_user_loses_the_access_token_on_refresh(
    auth: AuthService, store: FakeStore, revocations: FakeRevocations
) -> None:
    pair = await auth.register_customer("a@example.com", "Ana", PASSWORD)
    user = next(iter(store.users.values()))
    user.disabled = True
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(pair.refresh_token)
    assert set(revocations.revoked) == {"jti-1"}
