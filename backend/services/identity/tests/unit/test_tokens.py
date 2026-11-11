from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from identity.domain.user import User
from identity.infrastructure.security.jwt_issuer import JwtAccessTokenIssuer
from identity.infrastructure.security.keys import (
    SigningKeys,
    generate_private_pem,
    load_signing_keys,
)
from identity.infrastructure.security.password import Argon2idHasher

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def merchant() -> User:
    return User(
        id=uuid4(),
        email="m@example.com",
        name="M",
        password_hash="x",
        roles=frozenset({"merchant"}),
        merchant_id=uuid4(),
    )


def verifying_key(keys: SigningKeys) -> jwt.PyJWK:
    return jwt.PyJWK(keys.jwks()["keys"][0])


def test_access_token_carries_claims_and_verifies_with_the_published_jwk() -> None:
    keys = load_signing_keys("", [], allow_ephemeral=True)
    user = merchant()
    session = uuid4()
    token = JwtAccessTokenIssuer(keys, "iss", "aud", timedelta(minutes=5)).issue(user, session, NOW)
    header = jwt.get_unverified_header(token.token)
    assert header["alg"] == "EdDSA"
    assert header["kid"] == keys.kid
    claims = jwt.decode(
        token.token,
        verifying_key(keys).key,
        algorithms=["EdDSA"],
        audience="aud",
        issuer="iss",
        options={"verify_exp": False, "verify_nbf": False, "verify_iat": False},
    )
    assert claims["sub"] == str(user.id)
    assert claims["merchant_id"] == str(user.merchant_id)
    assert claims["roles"] == ["merchant"]
    assert "stock:write:own" in claims["scope"].split()
    assert claims["exp"] - claims["iat"] == 300
    assert claims["sid"] == str(session)
    assert token.expires_in == 300


def test_token_signed_by_another_key_does_not_verify() -> None:
    keys = load_signing_keys("", [], allow_ephemeral=True)
    attacker = load_signing_keys("", [], allow_ephemeral=True)
    token = JwtAccessTokenIssuer(attacker, "iss", "aud").issue(merchant(), uuid4(), NOW)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            token.token,
            verifying_key(keys).key,
            algorithms=["EdDSA"],
            audience="aud",
            options={"verify_exp": False},
        )


def test_key_loaded_from_pem_is_stable_and_retired_keys_stay_in_the_jwks() -> None:
    pem = generate_private_pem()
    first = load_signing_keys(pem, [], allow_ephemeral=False)
    again = load_signing_keys(pem.replace("\n", "\\n"), [], allow_ephemeral=False)
    assert first.kid == again.kid
    old = Ed25519PrivateKey.generate()
    old_pem = (
        old.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    rotated = load_signing_keys(pem, [old_pem], allow_ephemeral=False)
    assert len(rotated.jwks()["keys"]) == 2
    assert rotated.jwks()["keys"][0]["kid"] == first.kid


def test_ephemeral_keys_are_refused_outside_development() -> None:
    with pytest.raises(RuntimeError):
        load_signing_keys("", [], allow_ephemeral=False)


def test_jwks_never_exposes_private_material() -> None:
    keys = load_signing_keys("", [], allow_ephemeral=True)
    assert set(keys.jwks()["keys"][0]) == {"kty", "crv", "x", "kid", "use", "alg"}


async def test_argon2id_hashes_verify_and_are_salted() -> None:
    hasher = Argon2idHasher(time_cost=1, memory_kib=8, parallelism=1)
    first = await hasher.hash("correct horse battery")
    second = await hasher.hash("correct horse battery")
    assert first.startswith("$argon2id$")
    assert first != second
    assert await hasher.verify(first, "correct horse battery")
    assert not await hasher.verify(first, "wrong")
    assert not await hasher.verify("not-a-hash", "wrong")
    assert not hasher.needs_rehash(first)
    assert Argon2idHasher(time_cost=2, memory_kib=8, parallelism=1).needs_rehash(first)
