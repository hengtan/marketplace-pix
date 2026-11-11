from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from notifications.domain.contact import Contact
from notifications.domain.errors import InvalidContact
from notifications.domain.factory import build_notification, notification_id_for, order_ref
from notifications.domain.money import format_brl
from notifications.domain.notification import NotificationKind, NotificationStatus
from notifications.domain.order_projection import OrderItem, OrderProjection, OrderStatus
from notifications.domain.reasons import DEFAULT_REASON, translate_reason
from notifications.domain.retry import RetryPolicy

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
BASE_URL = "http://localhost:5173"


def make_order() -> OrderProjection:
    return OrderProjection(
        order_id=uuid4(),
        contact=Contact(uuid4(), "Maria da Silva", "maria@example.com"),
        currency="BRL",
        total_cents=44980,
        items=[OrderItem("p1", 2, 17990), OrderItem("p2", 1, 9000, name="Cabo USB-C")],
        created_at=NOW,
    )


@pytest.mark.parametrize(
    ("cents", "expected"),
    [
        (0, "R$ 0,00"),
        (5, "R$ 0,05"),
        (99, "R$ 0,99"),
        (34990, "R$ 349,90"),
        (100000, "R$ 1.000,00"),
        (123456789, "R$ 1.234.567,89"),
    ],
)
def test_format_brl(cents: int, expected: str) -> None:
    assert format_brl(cents) == expected


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("out of stock", "estoque insuficiente"),
        ("payment expired", "o PIX expirou"),
        ("  Out Of Stock ", "estoque insuficiente"),
        ("something new", DEFAULT_REASON),
        ("", DEFAULT_REASON),
        (None, DEFAULT_REASON),
    ],
)
def test_translate_reason(reason: str | None, expected: str) -> None:
    assert translate_reason(reason) == expected


def test_contact_rejects_invalid_email_and_blank_name() -> None:
    with pytest.raises(InvalidContact):
        Contact(uuid4(), "Maria", "not-an-email")
    with pytest.raises(InvalidContact):
        Contact(uuid4(), "  ", "maria@example.com")
    assert Contact(uuid4(), "Maria da Silva", "maria@example.com").first_name == "Maria"


def test_retry_policy_backoff_is_exponential_and_capped() -> None:
    policy = RetryPolicy(max_attempts=5, base_seconds=2, cap_seconds=10)
    assert [policy.delay_after(n) for n in (1, 2, 3, 4)] == [2, 4, 8, 10]
    assert not policy.exhausted(4)
    assert policy.exhausted(5)


def test_projection_only_leaves_pending_once() -> None:
    order = make_order()
    order.mark_paid(NOW)
    order.mark_cancelled("out of stock", NOW)
    assert order.status is OrderStatus.PAID
    assert order.cancelled_at is None


def test_notification_id_is_deterministic_per_event_and_kind() -> None:
    event_id = uuid4()
    assert notification_id_for(event_id, NotificationKind.PIX_READY) == notification_id_for(
        event_id, NotificationKind.PIX_READY
    )
    assert notification_id_for(event_id, NotificationKind.PIX_READY) != notification_id_for(
        event_id, NotificationKind.ORDER_PAID
    )


def test_order_created_notification_summarises_the_order() -> None:
    order = make_order()
    notification = build_notification(
        NotificationKind.ORDER_CREATED, uuid4(), order, NOW, base_url=BASE_URL
    )
    assert notification.status is NotificationStatus.QUEUED
    assert notification.subject == f"Recebemos o seu pedido #{order_ref(order.order_id)}"
    assert notification.context["customer_name"] == "Maria"
    assert notification.context["items"][0]["name"] == "Item 1"
    assert notification.context["items"][1]["name"] == "Cabo USB-C"
    assert notification.context["items"][0]["line_total_cents"] == 35980
    assert notification.context["action_url"] == f"{BASE_URL}/pedidos/{order.order_id}"


def test_pix_ready_carries_code_amount_and_expiry() -> None:
    order = make_order()
    expires = NOW + timedelta(minutes=30)
    notification = build_notification(
        NotificationKind.PIX_READY,
        uuid4(),
        order,
        NOW,
        base_url=BASE_URL,
        pix_code="000201PIXCODE",
        pix_amount_cents=44980,
        pix_expires_at=expires,
    )
    assert notification.context["pix_code"] == "000201PIXCODE"
    assert notification.context["pix_amount_cents"] == 44980
    assert notification.context["pix_expires_at"] == expires.isoformat()


def test_cancelled_notification_translates_the_reason() -> None:
    notification = build_notification(
        NotificationKind.ORDER_CANCELLED,
        uuid4(),
        make_order(),
        NOW,
        base_url=BASE_URL,
        reason="payment expired",
    )
    assert notification.context["reason_text"] == "o PIX expirou"
    assert notification.context["action_url"] == BASE_URL


def test_failures_back_off_and_end_in_failed_after_five_attempts() -> None:
    policy = RetryPolicy(base_seconds=2)
    notification = build_notification(
        NotificationKind.ORDER_PAID, uuid4(), make_order(), NOW, base_url=BASE_URL
    )
    delays = []
    for _ in range(4):
        notification.record_failure("smtp down", NOW, policy)
        assert notification.status is NotificationStatus.QUEUED
        delays.append((notification.next_attempt_at - NOW).total_seconds())
    assert delays == [2, 4, 8, 16]
    notification.record_failure("smtp down", NOW, policy)
    assert notification.status is NotificationStatus.FAILED
    assert notification.attempts == 5


def test_mark_sent_records_time_and_clears_error() -> None:
    notification = build_notification(
        NotificationKind.ORDER_PAID, uuid4(), make_order(), NOW, base_url=BASE_URL
    )
    notification.record_failure("boom", NOW, RetryPolicy())
    notification.mark_sent(NOW)
    assert notification.status is NotificationStatus.SENT
    assert notification.sent_at == NOW
    assert notification.last_error is None
