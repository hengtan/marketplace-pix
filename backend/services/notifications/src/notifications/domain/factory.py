from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from notifications.domain.notification import Notification, NotificationKind
from notifications.domain.order_projection import OrderProjection
from notifications.domain.reasons import translate_reason

SUBJECTS: dict[NotificationKind, str] = {
    NotificationKind.ORDER_CREATED: "Recebemos o seu pedido #{ref}",
    NotificationKind.PIX_READY: "Seu PIX do pedido #{ref} está pronto",
    NotificationKind.ORDER_PAID: "Pagamento confirmado para o pedido #{ref}",
    NotificationKind.ORDER_CANCELLED: "Seu pedido #{ref} foi cancelado",
}

ACTION_LABELS: dict[NotificationKind, str] = {
    NotificationKind.ORDER_CREATED: "Acompanhar pedido",
    NotificationKind.PIX_READY: "Ir para o pagamento",
    NotificationKind.ORDER_PAID: "Ver meu pedido",
    NotificationKind.ORDER_CANCELLED: "Voltar para a loja",
}


def order_ref(order_id: UUID) -> str:
    return str(order_id)[:8].upper()


def subject_for(kind: NotificationKind, order_id: UUID) -> str:
    return SUBJECTS[kind].format(ref=order_ref(order_id))


def notification_id_for(event_id: UUID, kind: NotificationKind) -> UUID:
    return uuid5(NAMESPACE_URL, f"marketplace-pix:notification:{event_id}:{kind.value}")


def build_notification(
    kind: NotificationKind,
    event_id: UUID,
    order: OrderProjection,
    now: datetime,
    *,
    base_url: str,
    pix_code: str | None = None,
    pix_amount_cents: int | None = None,
    pix_expires_at: datetime | None = None,
    reason: str | None = None,
) -> Notification:
    base = base_url.rstrip("/")
    action_url = (
        base if kind is NotificationKind.ORDER_CANCELLED else f"{base}/pedidos/{order.order_id}"
    )
    context: dict[str, Any] = {
        "customer_name": order.contact.first_name,
        "order_ref": order_ref(order.order_id),
        "order_id": str(order.order_id),
        "currency": order.currency,
        "total_cents": order.total_cents,
        "items": [
            {
                "name": item.name or f"Item {position}",
                "quantity": item.quantity,
                "unit_price_cents": item.unit_price_cents,
                "line_total_cents": item.line_total_cents,
            }
            for position, item in enumerate(order.items, start=1)
        ],
        "action_url": action_url,
        "action_label": ACTION_LABELS[kind],
    }
    if kind is NotificationKind.PIX_READY:
        context["pix_code"] = pix_code
        context["pix_amount_cents"] = (
            order.total_cents if pix_amount_cents is None else pix_amount_cents
        )
        context["pix_expires_at"] = pix_expires_at.isoformat() if pix_expires_at else None
    if kind is NotificationKind.ORDER_CANCELLED:
        context["reason_text"] = translate_reason(reason)
    return Notification(
        id=notification_id_for(event_id, kind),
        event_id=event_id,
        kind=kind,
        order_id=order.order_id,
        recipient=order.contact,
        subject=subject_for(kind, order.order_id),
        context=context,
        created_at=now,
        next_attempt_at=now,
    )
