from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from marketplace_common.security import Principal, scopes_for_roles, sign_principal

from identity.application.auth import AuthPolicy, AuthService
from identity.interface.api import create_app, merchant_id_for_slug
from tests.fakes import FakeHasher, FakeIssuer, FakeStore, FakeUow, MutableClock

PASSWORD = "correct horse battery"
SECRET = "internal-secret"


@pytest.fixture
def client() -> Iterator[TestClient]:
    store = FakeStore()
    auth = AuthService(
        lambda: FakeUow(store), FakeHasher(), FakeIssuer(), AuthPolicy(), MutableClock()
    )
    app = create_app(auth=auth, jwks={"keys": []}, internal_secret=SECRET)
    with TestClient(app) as test_client:
        yield test_client


def signed(roles: set[str], user_id: Any = None, request_id: str = "rid") -> dict[str, str]:
    principal = Principal(
        user_id or uuid4(), frozenset(roles), scopes_for_roles(frozenset(roles)), None
    )
    return {**sign_principal(SECRET, principal, request_id), "x-request-id": request_id}


def register(client: TestClient, email: str = "ana@example.com") -> dict[str, Any]:
    response = client.post(
        "/auth/register", json={"email": email, "name": "Ana", "password": PASSWORD}
    )
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def test_register_and_login_return_tokens_without_caching(client: TestClient) -> None:
    body = register(client)
    assert body["token_type"] == "Bearer"
    assert body["user"]["roles"] == ["customer"]
    assert "password" not in str(body)
    login = client.post("/auth/login", json={"email": "ana@example.com", "password": PASSWORD})
    assert login.status_code == 200
    assert login.headers["cache-control"] == "no-store"


def test_login_failures_do_not_reveal_whether_the_email_exists(client: TestClient) -> None:
    register(client)
    wrong_password = client.post(
        "/auth/login", json={"email": "ana@example.com", "password": "wrong password"}
    )
    unknown = client.post("/auth/login", json={"email": "who@example.com", "password": PASSWORD})
    assert wrong_password.status_code == unknown.status_code == 401
    assert wrong_password.json() == unknown.json()


def test_duplicate_registration_is_409_and_weak_password_is_422(client: TestClient) -> None:
    register(client)
    duplicate = client.post(
        "/auth/register", json={"email": "ana@example.com", "name": "A", "password": PASSWORD}
    )
    assert duplicate.status_code == 409
    weak = client.post(
        "/auth/register", json={"email": "b@example.com", "name": "B", "password": "short"}
    )
    assert weak.status_code == 422
    assert "at least" in weak.json()["detail"]


def test_refresh_rotates_and_reuse_is_rejected(client: TestClient) -> None:
    first = register(client)
    rotated = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert rotated.status_code == 200
    reused = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reused.status_code == 401
    after = client.post("/auth/refresh", json={"refresh_token": rotated.json()["refresh_token"]})
    assert after.status_code == 401


def test_logout_then_refresh_fails(client: TestClient) -> None:
    body = register(client)
    assert (
        client.post("/auth/logout", json={"refresh_token": body["refresh_token"]}).status_code
        == 204
    )
    assert (
        client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code
        == 401
    )


def test_me_requires_a_gateway_signed_identity(client: TestClient) -> None:
    body = register(client)
    assert client.get("/auth/me").status_code == 401
    forged = client.get("/auth/me", headers={"x-user-id": body["user"]["id"]})
    assert forged.status_code == 401
    ok = client.get("/auth/me", headers=signed({"customer"}, user_id=UUID(body["user"]["id"])))
    assert ok.status_code == 200
    assert ok.json()["email"] == "ana@example.com"


def test_admin_user_creation_needs_the_users_manage_scope(client: TestClient) -> None:
    payload = {
        "email": "shop@example.com",
        "name": "Shop",
        "password": PASSWORD,
        "roles": ["merchant"],
        "merchant_slug": "trilha-sports",
    }
    assert client.post("/auth/admin/users", json=payload).status_code == 401
    assert (
        client.post("/auth/admin/users", json=payload, headers=signed({"customer"})).status_code
        == 403
    )
    assert (
        client.post("/auth/admin/users", json=payload, headers=signed({"merchant"})).status_code
        == 403
    )
    created = client.post("/auth/admin/users", json=payload, headers=signed({"admin"}))
    assert created.status_code == 201
    assert created.json()["merchant_id"] == str(merchant_id_for_slug("trilha-sports"))


def test_jwks_is_public(client: TestClient) -> None:
    response = client.get("/.well-known/jwks.json")
    assert response.status_code == 200
    assert response.json() == {"keys": []}


def test_register_ignores_a_client_supplied_role(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={
            "email": "sneaky@example.com",
            "name": "Sneaky",
            "password": PASSWORD,
            "roles": ["admin"],
            "merchant_id": str(uuid4()),
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["roles"] == ["customer"]
    assert response.json()["user"]["merchant_id"] is None
