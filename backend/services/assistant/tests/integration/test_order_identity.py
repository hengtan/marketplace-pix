from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from marketplace_common.security import (
    Principal,
    scopes_for_roles,
    sign_principal,
    verify_principal,
)

from assistant.config import Settings
from assistant.infrastructure.fixtures import FixtureInventoryGateway
from assistant.interface.api import create_app
from assistant.wiring import build_container

SECRET = "test-internal-secret"


class FakeOrdering:
    """Imita o ordering: pedido de conta só para o dono, pedido de convidado para quem tem o id."""

    def __init__(self) -> None:
        self.owners: dict[UUID, UUID | None] = {}
        self.calls: list[Principal | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        order_id = UUID(request.url.path.rsplit("/", 1)[-1])
        principal = verify_principal(
            SECRET, dict(request.headers), request.headers.get("x-request-id", "")
        )
        self.calls.append(principal)
        if order_id not in self.owners:
            return httpx.Response(404)
        owner = self.owners[order_id]
        if owner is not None and (principal is None or principal.user_id != owner):
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "id": str(order_id),
                "status": "PAID",
                "total_cents": 34990,
                "currency": "BRL",
                "created_at": "2026-11-01T10:00:00Z",
                "cancel_reason": None,
                "items": [{"quantity": 1}],
            },
        )


def signed(user: UUID, request_id: str = "req-1") -> dict[str, str]:
    principal = Principal(user, frozenset({"customer"}), scopes_for_roles(frozenset({"customer"})))
    return {**sign_principal(SECRET, principal, request_id), "x-request-id": request_id}


@pytest.fixture
def ordering() -> FakeOrdering:
    return FakeOrdering()


@pytest.fixture
async def chat(settings, engine, catalog, snapshot_products, ordering):  # type: ignore[no-untyped-def]
    http = httpx.AsyncClient(transport=httpx.MockTransport(ordering))
    built = build_container(
        Settings(assistant_db=settings.assistant_db, internal_auth_secret=SECRET),  # type: ignore[call-arg]
        engine,
        catalog=catalog,
        inventory=FixtureInventoryGateway(snapshot_products),
        http_client=http,
        token_delay_seconds=0.0,
    )
    await built.ingest.execute()
    app = create_app(container=built, internal_secret=SECRET)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
    await built.aclose()
    await http.aclose()


async def ask(chat: httpx.AsyncClient, order: UUID, headers: dict[str, str] | None = None) -> str:
    response = await chat.post(
        "/chat", json={"message": f"status do pedido {order}"}, headers=headers or {}
    )
    assert response.status_code == 200
    return str(response.json()["answer"])


async def test_an_authenticated_user_sees_their_own_order(chat, ordering) -> None:  # type: ignore[no-untyped-def]
    user, order = uuid4(), uuid4()
    ordering.owners[order] = user
    answer = await ask(chat, order, signed(user))
    assert "está pago" in answer and "R$ 349,90" in answer
    assert ordering.calls[-1] is not None and ordering.calls[-1].user_id == user


async def test_another_user_cannot_read_the_order_through_the_chat(chat, ordering) -> None:  # type: ignore[no-untyped-def]
    owner, intruder, order = uuid4(), uuid4(), uuid4()
    ordering.owners[order] = owner
    answer = await ask(chat, order, signed(intruder))
    assert "Não encontrei" in answer
    assert "está pago" not in answer and "349,90" not in answer


async def test_an_anonymous_caller_cannot_read_an_account_order(chat, ordering) -> None:  # type: ignore[no-untyped-def]
    order = uuid4()
    ordering.owners[order] = uuid4()
    answer = await ask(chat, order)
    assert "Não encontrei" in answer
    assert ordering.calls[-1] is None


async def test_unsigned_or_forged_identity_headers_are_treated_as_anonymous(  # type: ignore[no-untyped-def]
    chat, ordering
) -> None:
    owner, order = uuid4(), uuid4()
    ordering.owners[order] = owner
    forged = {"x-user-id": str(owner), "x-user-roles": "customer", "x-request-id": "req-1"}
    assert "Não encontrei" in await ask(chat, order, forged)
    wrong_key = Principal(owner, frozenset({"customer"}), frozenset())
    bad = {**sign_principal("another-secret", wrong_key, "req-1"), "x-request-id": "req-1"}
    assert "Não encontrei" in await ask(chat, order, bad)
    assert ordering.calls == [None, None]


async def test_a_guest_order_is_still_found_by_id(chat, ordering) -> None:  # type: ignore[no-untyped-def]
    order = uuid4()
    ordering.owners[order] = None
    assert "está pago" in await ask(chat, order)
    assert "está pago" in await ask(chat, order, signed(uuid4()))


async def test_the_stream_endpoint_forwards_the_identity_too(chat, ordering) -> None:  # type: ignore[no-untyped-def]
    user, order = uuid4(), uuid4()
    ordering.owners[order] = user
    response = await chat.post(
        "/chat/stream", json={"message": f"status do pedido {order}"}, headers=signed(user)
    )
    assert "está pago" in response.text.replace("\\u00e1", "á")
    other = await chat.post(
        "/chat/stream", json={"message": f"status do pedido {order}"}, headers=signed(uuid4())
    )
    assert "está pago" not in other.text.replace("\\u00e1", "á")
