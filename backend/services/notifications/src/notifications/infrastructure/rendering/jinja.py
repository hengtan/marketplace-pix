from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from notifications.application.ports import DailySummary, RenderedEmail
from notifications.domain.factory import subject_for
from notifications.domain.money import format_brl
from notifications.domain.notification import NotificationKind

TEMPLATES_DIR = Path(__file__).parent / "templates"


class JinjaEmailRenderer:
    def __init__(self, timezone: str = "America/Sao_Paulo") -> None:
        self._tz = ZoneInfo(timezone)
        self._env = Environment(
            loader=FileSystemLoader(TEMPLATES_DIR),
            autoescape=lambda name: bool(name and name.endswith(".html.j2")),
            undefined=StrictUndefined,
            keep_trailing_newline=True,
        )
        self._env.filters["brl"] = format_brl
        self._env.filters["datetime_br"] = self._datetime_br
        self._env.filters["date_br"] = self._date_br

    def _datetime_br(self, value: str | datetime) -> str:
        moment = datetime.fromisoformat(value) if isinstance(value, str) else value
        return moment.astimezone(self._tz).strftime("%d/%m/%Y às %H:%M")

    @staticmethod
    def _date_br(value: str | date) -> str:
        day = date.fromisoformat(value) if isinstance(value, str) else value
        return day.strftime("%d/%m/%Y")

    def _render_pair(self, name: str, context: dict[str, Any]) -> RenderedEmail:
        return RenderedEmail(
            html=self._env.get_template(f"{name}.html.j2").render(context),
            text=self._env.get_template(f"{name}.txt.j2").render(context),
        )

    def render(self, kind: NotificationKind, context: dict[str, Any]) -> RenderedEmail:
        subject = subject_for(kind, UUID(context["order_id"]))
        return self._render_pair(kind.value.lower(), {**context, "subject": subject})

    def render_daily_summary(self, summary: DailySummary) -> RenderedEmail:
        stats = summary.stats
        context = {
            "day": summary.day.isoformat(),
            "created": stats.created,
            "paid": stats.paid,
            "cancelled": stats.cancelled,
            "paid_cents": stats.paid_cents,
            "rows": [
                ("Pedidos criados", stats.created),
                ("Pedidos pagos", stats.paid),
                ("Pedidos cancelados", stats.cancelled),
            ],
        }
        return self._render_pair("daily_summary", context)
