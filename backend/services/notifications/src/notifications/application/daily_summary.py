from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from notifications.application.clock import Clock, utcnow
from notifications.application.ports import (
    DailySummary,
    EmailRenderer,
    EmailSender,
    OutgoingEmail,
    UnitOfWork,
)
from notifications.domain.factory import daily_summary_subject


class SendDailySalesSummary:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        renderer: EmailRenderer,
        sender: EmailSender,
        admin_email: str,
        timezone: str = "America/Sao_Paulo",
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._renderer = renderer
        self._sender = sender
        self._admin_email = admin_email
        self._tz = ZoneInfo(timezone)
        self._clock = clock

    def today(self) -> date:
        return self._clock().astimezone(self._tz).date()

    async def execute(self, day: date | None = None) -> DailySummary:
        day = day or self.today()
        start = datetime.combine(day, time.min, tzinfo=self._tz).astimezone(UTC)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=self._tz).astimezone(UTC)
        async with self._uow_factory() as uow:
            stats = await uow.orders.stats_between(start, end)
        summary = DailySummary(day=day, stats=stats)
        rendered = self._renderer.render_daily_summary(summary)
        await self._sender.send(
            OutgoingEmail(
                to_email=self._admin_email,
                to_name="Administração",
                subject=daily_summary_subject(day),
                html=rendered.html,
                text=rendered.text,
            )
        )
        return summary
