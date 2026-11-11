from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from notifications.application.ports import DailyStats, DailySummary
from notifications.domain.contact import Contact
from notifications.domain.factory import build_notification
from notifications.domain.notification import Notification, NotificationKind
from notifications.domain.order_projection import OrderItem, OrderProjection
from notifications.infrastructure.rendering.jinja import TEMPLATES_DIR, JinjaEmailRenderer

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
PIX_CODE = "00020126580014br.gov.bcb.pix0136a1b2c3d4-0000-4000-8000-000000000000520400005303986"


def order(name: str = "Maria da Silva") -> OrderProjection:
    return OrderProjection(
        order_id=uuid4(),
        contact=Contact(uuid4(), name, "maria@example.com"),
        currency="BRL",
        total_cents=394_880,
        items=[
            OrderItem("p1", 2, 34990, name="Fone Bluetooth Nova ANC"),
            OrderItem("p2", 1, 324_900),
        ],
        created_at=NOW,
    )


def notification(kind: NotificationKind, order_: OrderProjection | None = None) -> Notification:
    return build_notification(
        kind,
        uuid4(),
        order_ or order(),
        NOW,
        base_url="http://localhost:5173",
        pix_code=PIX_CODE,
        pix_amount_cents=394_880,
        pix_expires_at=datetime(2026, 11, 11, 17, 30, tzinfo=UTC),
        reason="out of stock",
    )


@pytest.fixture
def renderer() -> JinjaEmailRenderer:
    return JinjaEmailRenderer("America/Sao_Paulo")


@pytest.mark.parametrize("kind", list(NotificationKind))
def test_every_kind_renders_responsive_html_and_plain_text(
    renderer: JinjaEmailRenderer, kind: NotificationKind
) -> None:
    n = notification(kind)
    email = renderer.render(kind, n.context)

    assert email.html.startswith("<!doctype html>")
    assert 'name="viewport"' in email.html
    assert "@media" in email.html
    assert 'role="presentation"' in email.html
    assert n.context["action_url"] in email.html
    assert n.context["action_label"] in email.html
    assert "Maria" in email.html and "Maria" in email.text
    assert n.context["order_ref"] in email.text
    assert n.context["action_url"] in email.text


@pytest.mark.parametrize("kind", list(NotificationKind))
def test_order_summary_formats_values_in_reais(
    renderer: JinjaEmailRenderer, kind: NotificationKind
) -> None:
    email = renderer.render(kind, notification(kind).context)

    for rendered in (email.html, email.text):
        assert "R$ 3.948,80" in rendered
        assert "R$ 349,90" in rendered
        assert "R$ 699,80" in rendered
        assert "R$ 3.249,00" in rendered
    assert "Fone Bluetooth Nova ANC" in email.html
    assert "Item 2" in email.html


def test_pix_ready_shows_code_amount_and_expiry_in_local_time(
    renderer: JinjaEmailRenderer,
) -> None:
    email = renderer.render(
        NotificationKind.PIX_READY, notification(NotificationKind.PIX_READY).context
    )

    assert PIX_CODE in email.html and PIX_CODE in email.text
    assert "PIX Copia e Cola" in email.html
    assert "11/11/2026 às 14:30" in email.html
    assert "11/11/2026 às 14:30" in email.text


def test_cancelled_shows_friendly_reason(renderer: JinjaEmailRenderer) -> None:
    n = notification(NotificationKind.ORDER_CANCELLED)
    email = renderer.render(n.kind, n.context)
    assert "estoque insuficiente" in email.html
    assert "estoque insuficiente" in email.text
    assert "out of stock" not in email.html

    expired = build_notification(
        NotificationKind.ORDER_CANCELLED,
        uuid4(),
        order(),
        NOW,
        base_url="http://x.test",
        reason="payment expired",
    )
    assert "o PIX expirou" in renderer.render(expired.kind, expired.context).html


def test_paid_confirms_the_amount(renderer: JinjaEmailRenderer) -> None:
    n = notification(NotificationKind.ORDER_PAID)
    email = renderer.render(n.kind, n.context)
    assert "Pagamento aprovado" in email.html
    assert "R$ 3.948,80" in email.text


def test_html_output_escapes_user_provided_values(renderer: JinjaEmailRenderer) -> None:
    n = notification(NotificationKind.ORDER_CREATED, order(name="<script>alert(1)</script> Eva"))
    email = renderer.render(n.kind, n.context)
    assert "<script>" not in email.html
    assert "&lt;script&gt;" in email.html


def test_daily_summary_renders_the_numbers(renderer: JinjaEmailRenderer) -> None:
    email = renderer.render_daily_summary(
        DailySummary(
            date(2026, 11, 11), DailyStats(created=7, paid=4, cancelled=2, paid_cents=129_990)
        )
    )
    for rendered in (email.html, email.text):
        assert "11/11/2026" in rendered
        assert "R$ 1.299,90" in rendered
        assert "Pedidos criados" in rendered
    assert ">7<" in email.html and ">4<" in email.html and ">2<" in email.html


def test_templates_and_rendered_copy_have_no_long_dashes(renderer: JinjaEmailRenderer) -> None:
    for path in Path(TEMPLATES_DIR).iterdir():
        content = path.read_text(encoding="utf-8")
        assert "—" not in content and "–" not in content, path.name
    for kind in NotificationKind:
        email = renderer.render(kind, notification(kind).context)
        assert "—" not in email.html + email.text
        assert "–" not in email.html + email.text
