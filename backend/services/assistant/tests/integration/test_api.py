import json
import logging
from uuid import UUID, uuid4

import httpx

from assistant.application.ports import OrderInfo


def parse_sse(body: str) -> list[tuple[str, dict]]:  # type: ignore[type-arg]
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        events.append(
            (lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: ")))
        )
    return events


async def test_chat_returns_answer_citations_trace_and_retrieved(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/chat", json={"message": "quero um fone com cancelamento de ruído"}
    )
    assert response.status_code == 200
    body = response.json()
    UUID(body["session_id"])
    assert "Fone Bluetooth Nova ANC" in body["answer"] and "R$ 349,90" in body["answer"]
    assert body["citations"][0]["slug"] == "fone-bluetooth-nova"
    assert body["citations"][0]["score"] > 0
    assert [t["name"] for t in body["tool_calls"]] == ["search_products"]
    assert body["tool_calls"][0]["arguments"]["query"].startswith("quero um fone")
    assert body["tool_calls"][0]["duration_ms"] >= 0
    assert body["retrieved"][0]["slug"] == "fone-bluetooth-nova"
    assert body["latency_ms"] >= 0


async def test_chat_without_context_says_it_did_not_find(client: httpx.AsyncClient) -> None:
    body = (await client.post("/chat", json={"message": "qual a capital da França?"})).json()
    assert body["answer"].startswith("Só consigo ajudar")
    assert body["citations"] == [] and body["retrieved"] == [] and body["tool_calls"] == []


async def test_stock_question_uses_two_tools(client: httpx.AsyncClient) -> None:
    body = (await client.post("/chat", json={"message": "tem estoque do relógio GPS?"})).json()
    assert [t["name"] for t in body["tool_calls"]] == ["search_products", "get_stock"]
    assert "Restam apenas 3 unidades de Relógio GPS Trail" in body["answer"]


async def test_order_status_tool(client: httpx.AsyncClient, orders) -> None:  # type: ignore[no-untyped-def]
    order_id = uuid4()
    orders.orders[order_id] = OrderInfo(order_id, "PAID", 34990, "BRL", 1, "2026-11-01", None)
    body = (await client.post("/chat", json={"message": f"status do pedido {order_id}"})).json()
    assert [t["name"] for t in body["tool_calls"]] == ["get_order_status"]
    assert "está pago" in body["answer"] and "R$ 349,90" in body["answer"]
    assert "@" not in json.dumps(body)


async def test_memory_resolves_references_across_messages(client: httpx.AsyncClient) -> None:
    first = (
        await client.post("/chat", json={"message": "quero um fone com cancelamento de ruído"})
    ).json()
    follow = (
        await client.post(
            "/chat", json={"session_id": first["session_id"], "message": "e esse tem estoque?"}
        )
    ).json()
    assert follow["session_id"] == first["session_id"]
    assert [t["name"] for t in follow["tool_calls"]] == ["get_stock"]
    assert "Fone Bluetooth Nova ANC" in follow["answer"]

    again = (
        await client.post(
            "/chat", json={"session_id": first["session_id"], "message": "e esse tem estoque?"}
        )
    ).json()
    assert "Fone Bluetooth Nova ANC" in again["answer"], "stock turns keep the product in memory"


async def test_session_endpoint_returns_history(client: httpx.AsyncClient) -> None:
    first = (await client.post("/chat", json={"message": "luminária para sala"})).json()
    sid = first["session_id"]
    await client.post("/chat", json={"session_id": sid, "message": "mochila para trilha"})
    session = (await client.get(f"/sessions/{sid}")).json()
    assert session["session_id"] == sid
    assert [m["role"] for m in session["messages"]] == ["user", "assistant", "user", "assistant"]
    assert session["messages"][0]["content"] == "luminária para sala"
    assert session["messages"][1]["tool_calls"][0]["name"] == "search_products"


async def test_unknown_session_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/sessions/{uuid4()}")
    assert response.status_code == 404 and response.json() == {"detail": "session not found"}


async def test_message_validation(client: httpx.AsyncClient) -> None:
    for message in ("", "   ", "x" * 1001):
        response = await client.post("/chat", json={"message": message})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)
    assert (await client.post("/chat", json={})).status_code == 422
    assert (await client.post("/chat", json={"message": "x" * 1000})).status_code == 200


async def test_stream_emits_tool_call_token_and_done_in_order(client: httpx.AsyncClient) -> None:
    response = await client.post("/chat/stream", json={"message": "tem estoque do relógio GPS?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    kinds = [kind for kind, _ in events]
    assert kinds[:2] == ["tool_call", "tool_call"]
    assert kinds[-1] == "done" and kinds.count("done") == 1
    tokens = [data["text"] for kind, data in events if kind == "token"]
    assert len(tokens) > 3
    done = events[-1][1]
    assert "".join(tokens).strip() == done["answer"].strip()
    assert [t["name"] for t in done["tool_calls"]] == ["search_products", "get_stock"]
    session = (await client.get(f"/sessions/{done['session_id']}")).json()
    assert len(session["messages"]) == 2


async def test_stream_rejects_invalid_message_before_streaming(client: httpx.AsyncClient) -> None:
    assert (await client.post("/chat/stream", json={"message": ""})).status_code == 422


async def test_reindex_reports_counts(client: httpx.AsyncClient, catalog) -> None:  # type: ignore[no-untyped-def]
    body = (await client.post("/admin/reindex")).json()
    assert body["indexed"] == 0 and body["removed"] == 0 and body["skipped"] > 0
    catalog.products = [p for p in catalog.products if p.slug != "vaso-ceramica-terra"]
    body = (await client.post("/admin/reindex")).json()
    assert body["removed"] >= 1


async def test_evals_latest_is_404_until_a_run_exists(client: httpx.AsyncClient) -> None:
    assert (await client.get("/evals/latest")).status_code == 404


async def test_health_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).json() == {"ready": True}


async def test_logs_do_not_contain_message_text_or_personal_data(
    client: httpx.AsyncClient, caplog
) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG)
    secret = "meu email é joao.silva@example.com e quero um fone com cancelamento de ruído"
    await client.post("/chat", json={"message": secret})
    assert "joao.silva" not in caplog.text
    assert "cancelamento" not in caplog.text
    assert "chat done" in caplog.text
