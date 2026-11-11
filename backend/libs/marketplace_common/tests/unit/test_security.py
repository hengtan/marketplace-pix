from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from marketplace_common.security import (
    Principal,
    PrincipalResolver,
    Role,
    Scope,
    scopes_for_roles,
    sign_principal,
    strip_identity_headers,
    verify_principal,
)

SECRET = "s3cret"


def make_principal(roles: frozenset[str] = frozenset({"merchant"})) -> Principal:
    return Principal(uuid4(), roles, scopes_for_roles(roles), uuid4())


def test_signed_principal_round_trips() -> None:
    principal = make_principal()
    headers = sign_principal(SECRET, principal, "req-1", now=1000)
    assert verify_principal(SECRET, headers, "req-1", now=1010) == principal


def test_tampered_roles_are_rejected() -> None:
    headers = sign_principal(SECRET, make_principal(frozenset({"customer"})), "req-1", now=1000)
    headers["x-user-roles"] = "admin"
    assert verify_principal(SECRET, headers, "req-1", now=1000) is None


def test_signature_is_bound_to_the_request() -> None:
    headers = sign_principal(SECRET, make_principal(), "req-1", now=1000)
    assert verify_principal(SECRET, headers, "req-2", now=1000) is None


def test_expired_signature_is_rejected() -> None:
    headers = sign_principal(SECRET, make_principal(), "req-1", now=1000)
    assert verify_principal(SECRET, headers, "req-1", now=1000 + 61) is None


def test_wrong_secret_and_empty_secret_are_rejected() -> None:
    headers = sign_principal(SECRET, make_principal(), "req-1", now=1000)
    assert verify_principal("other", headers, "req-1", now=1000) is None
    assert verify_principal("", headers, "req-1", now=1000) is None


def test_unsigned_headers_are_anonymous() -> None:
    forged = {"x-user-id": str(uuid4()), "x-user-roles": "admin"}
    assert verify_principal(SECRET, forged, "req-1") is None


def test_strip_identity_headers_is_case_insensitive() -> None:
    kept = strip_identity_headers({"X-User-Id": "a", "x-auth-sig": "b", "Accept": "json"})
    assert kept == {"Accept": "json"}


def test_role_scopes() -> None:
    assert Scope.STOCK_WRITE_OWN.value in scopes_for_roles(frozenset({Role.MERCHANT.value}))
    assert Scope.LEDGER_RECONCILE.value not in scopes_for_roles(frozenset({"merchant"}))
    assert scopes_for_roles(frozenset({"unknown"})) == frozenset()


def test_catalog_write_scopes() -> None:
    assert Scope.CATALOG_WRITE_OWN.value in scopes_for_roles(frozenset({"merchant"}))
    assert Scope.CATALOG_WRITE_ANY.value not in scopes_for_roles(frozenset({"merchant"}))
    assert Scope.CATALOG_WRITE_ANY.value in scopes_for_roles(frozenset({"admin"}))
    assert Scope.CATALOG_WRITE_OWN.value not in scopes_for_roles(frozenset({"customer"}))


def test_resolver_as_fastapi_dependency() -> None:
    app = FastAPI()
    resolver = PrincipalResolver(SECRET)

    @app.get("/who")
    def who(principal: Principal | None = Depends(resolver)) -> dict[str, str | None]:  # noqa: B008
        return {"user": str(principal.user_id) if principal else None}

    client = TestClient(app)
    principal = make_principal()
    signed = sign_principal(SECRET, principal, "rid")
    assert client.get("/who", headers={**signed, "x-request-id": "rid"}).json() == {
        "user": str(principal.user_id)
    }
    assert client.get("/who", headers={**signed, "x-request-id": "other"}).json() == {"user": None}
    assert client.get("/who", headers={"x-user-id": str(uuid4())}).json() == {"user": None}
