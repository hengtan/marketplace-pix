from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from identity.application.auth import AuthPolicy, AuthService
from identity.application.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
    RefreshTokenReuse,
)
from identity.domain.errors import InvalidRoleAssignment, WeakPassword
from tests.fakes import FakeHasher, FakeIssuer, FakeStore, FakeUow, MutableClock

PASSWORD = "correct horse battery"


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def hasher() -> FakeHasher:
    return FakeHasher()


@pytest.fixture
def auth(store: FakeStore, hasher: FakeHasher, clock: MutableClock) -> AuthService:
    return AuthService(
        lambda: FakeUow(store),
        hasher,
        FakeIssuer(),
        AuthPolicy(
            refresh_ttl=timedelta(days=14),
            session_max=timedelta(days=30),
            max_failed_logins=3,
            lockout=timedelta(minutes=15),
        ),
        clock,
    )


async def test_register_creates_customer_and_session(auth: AuthService) -> None:
    pair = await auth.register_customer("  Ana@Example.COM ", "Ana", PASSWORD)
    assert pair.user.email == "ana@example.com"
    assert pair.user.roles == frozenset({"customer"})
    assert pair.refresh_token
    assert pair.expires_in == 600


async def test_register_never_stores_the_plain_password(
    auth: AuthService, store: FakeStore
) -> None:
    await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    assert all(u.password_hash != PASSWORD for u in store.users.values())


async def test_duplicate_email_is_rejected_case_insensitively(auth: AuthService) -> None:
    await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    with pytest.raises(EmailAlreadyRegistered):
        await auth.register_customer("ANA@example.com", "Outra", PASSWORD)


@pytest.mark.parametrize("password", ["short", "aaaaaaaaaaaa", "ana@example.com"])
async def test_weak_passwords_are_rejected(auth: AuthService, password: str) -> None:
    with pytest.raises(WeakPassword):
        await auth.register_customer("ana@example.com", "Ana", password)


async def test_seed_accounts_may_use_a_short_dev_password_but_the_policy_stays_on_by_default(
    auth: AuthService,
) -> None:
    with pytest.raises(WeakPassword):
        await auth.create_user(
            "lojista@example.com", "Lojista", "praca1234", frozenset({"merchant"})
        )
    await auth.create_user(
        "lojista@example.com",
        "Lojista",
        "praca1234",
        frozenset({"merchant"}),
        uuid4(),
        enforce_password_policy=False,
    )
    tokens = await auth.login("lojista@example.com", "praca1234")
    assert tokens.access_token


async def test_login_succeeds_and_wrong_password_fails(auth: AuthService) -> None:
    await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    assert (await auth.login("ana@example.com", PASSWORD)).user.email == "ana@example.com"
    with pytest.raises(InvalidCredentials):
        await auth.login("ana@example.com", "wrong password")


async def test_unknown_user_costs_the_same_hash_work(auth: AuthService, hasher: FakeHasher) -> None:
    before = hasher.verifications
    with pytest.raises(InvalidCredentials):
        await auth.login("nobody@example.com", PASSWORD)
    assert hasher.verifications == before + 1


async def test_account_locks_after_repeated_failures_and_recovers(
    auth: AuthService, clock: MutableClock
) -> None:
    await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    for _ in range(3):
        with pytest.raises(InvalidCredentials):
            await auth.login("ana@example.com", "bad password!")
    with pytest.raises(InvalidCredentials):
        await auth.login("ana@example.com", PASSWORD)
    clock.advance(minutes=16)
    assert (await auth.login("ana@example.com", PASSWORD)).access_token


async def test_refresh_rotates_the_token(auth: AuthService) -> None:
    first = await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    second = await auth.refresh(first.refresh_token)
    assert second.refresh_token != first.refresh_token
    third = await auth.refresh(second.refresh_token)
    assert third.refresh_token not in {first.refresh_token, second.refresh_token}


async def test_reusing_a_rotated_token_revokes_the_whole_family(auth: AuthService) -> None:
    first = await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    second = await auth.refresh(first.refresh_token)
    with pytest.raises(RefreshTokenReuse):
        await auth.refresh(first.refresh_token)
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(second.refresh_token)


async def test_other_sessions_survive_reuse_detection(auth: AuthService) -> None:
    await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    phone = await auth.login("ana@example.com", PASSWORD)
    laptop = await auth.login("ana@example.com", PASSWORD)
    rotated = await auth.refresh(phone.refresh_token)
    with pytest.raises(RefreshTokenReuse):
        await auth.refresh(phone.refresh_token)
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(rotated.refresh_token)
    assert (await auth.refresh(laptop.refresh_token)).access_token


async def test_refresh_token_expires(auth: AuthService, clock: MutableClock) -> None:
    pair = await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    clock.advance(days=15)
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(pair.refresh_token)


async def test_session_has_an_absolute_lifetime(auth: AuthService, clock: MutableClock) -> None:
    pair = await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    for _ in range(3):
        clock.advance(days=9)
        pair = await auth.refresh(pair.refresh_token)
    clock.advance(days=4)
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(pair.refresh_token)


async def test_unknown_refresh_token_is_rejected(auth: AuthService) -> None:
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh("not-a-token")


async def test_logout_revokes_the_session_and_is_idempotent(auth: AuthService) -> None:
    pair = await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    await auth.logout(pair.refresh_token)
    await auth.logout(pair.refresh_token)
    await auth.logout("garbage")
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(pair.refresh_token)


async def test_disabled_user_cannot_refresh(auth: AuthService, store: FakeStore) -> None:
    pair = await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    store.users[pair.user.id].disabled = True
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(pair.refresh_token)
    with pytest.raises(InvalidCredentials):
        await auth.login("ana@example.com", PASSWORD)


async def test_merchant_requires_merchant_id(auth: AuthService) -> None:
    with pytest.raises(InvalidRoleAssignment):
        await auth.create_user("m@example.com", "M", PASSWORD, frozenset({"merchant"}))
    user = await auth.create_user("m@example.com", "M", PASSWORD, frozenset({"merchant"}), uuid4())
    assert user.merchant_id is not None


async def test_customer_cannot_carry_a_merchant_id(auth: AuthService) -> None:
    with pytest.raises(InvalidRoleAssignment):
        await auth.create_user("c@example.com", "C", PASSWORD, frozenset({"customer"}), uuid4())


async def test_unknown_role_is_rejected(auth: AuthService) -> None:
    with pytest.raises(InvalidRoleAssignment):
        await auth.create_user("c@example.com", "C", PASSWORD, frozenset({"root"}))
