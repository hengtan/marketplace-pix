from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

from notifications.application.ports import EmailRenderer, EmailSender, UnitOfWork
from notifications.config import Settings, load_settings
from notifications.infrastructure.db.session import build_engine, build_session_factory
from notifications.infrastructure.db.uow import SqlAlchemyUnitOfWork
from notifications.infrastructure.mail.smtp import SmtpEmailSender
from notifications.infrastructure.rendering.jinja import JinjaEmailRenderer


@dataclass(frozen=True, slots=True)
class Runtime:
    settings: Settings
    uow_factory: Callable[[], UnitOfWork]
    renderer: EmailRenderer
    sender: EmailSender


@asynccontextmanager
async def runtime() -> AsyncIterator[Runtime]:
    """Builds the dependencies for a single task run.

    Each task calls ``asyncio.run`` and gets its own event loop, so the engine must not outlive it.
    """
    settings = load_settings()
    engine = build_engine(settings.database_url, pooled=False)
    factory = build_session_factory(engine)
    try:
        yield Runtime(
            settings=settings,
            uow_factory=lambda: SqlAlchemyUnitOfWork(factory),
            renderer=JinjaEmailRenderer(settings.timezone),
            sender=SmtpEmailSender(settings.smtp_host, settings.smtp_port, settings.mail_from),
        )
    finally:
        await engine.dispose()
