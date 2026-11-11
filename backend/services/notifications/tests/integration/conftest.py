import asyncio
import email
import socket
from collections.abc import Iterator
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from typing import Any

import pytest
from aiosmtpd.controller import Controller
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from notifications.config import Settings
from notifications.infrastructure.db.models import Base
from notifications.infrastructure.db.uow import SqlAlchemyUnitOfWork

TEST_DB = "notifications_test"


def _url(db: str) -> str:
    return Settings(notifications_db=db).database_url


async def _ensure_test_database() -> None:
    admin = create_async_engine(_url("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("select 1 from pg_database where datname = :n"), {"n": TEST_DB}
        )
        if not exists:
            await conn.execute(text(f'create database "{TEST_DB}"'))
    await admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    asyncio.run(_ensure_test_database())


@pytest.fixture
async def engine():
    engine: AsyncEngine = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(
            text("truncate notifications, order_projections, inbox_messages cascade")
        )
    await engine.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def uow_factory(session_factory):
    return lambda: SqlAlchemyUnitOfWork(session_factory)


@dataclass
class CapturedMail:
    mail_from: str
    rcpt_tos: list[str]
    message: EmailMessage

    @property
    def subject(self) -> str:
        return str(self.message["Subject"])

    @property
    def html(self) -> str:
        part = self.message.get_body(("html",))
        assert part is not None
        return str(part.get_content())

    @property
    def text(self) -> str:
        part = self.message.get_body(("plain",))
        assert part is not None
        return str(part.get_content())


@dataclass
class SmtpInbox:
    host: str
    port: int
    mails: list[CapturedMail] = field(default_factory=list)
    reject_recipients: bool = False
    temporary_failures: int = 0

    async def handle_RCPT(
        self, server: Any, session: Any, envelope: Any, address: str, rcpt_options: Any
    ) -> str:
        if self.reject_recipients:
            return "550 5.1.1 mailbox unavailable"
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        if self.temporary_failures > 0:
            self.temporary_failures -= 1
            return "451 4.3.0 try again later"
        message = email.message_from_bytes(envelope.content, policy=policy.default)
        assert isinstance(message, EmailMessage)
        self.mails.append(CapturedMail(envelope.mail_from, list(envelope.rcpt_tos), message))
        return "250 OK"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def smtp_server() -> Iterator[SmtpInbox]:
    inbox = SmtpInbox("127.0.0.1", free_port())
    controller = Controller(
        inbox, hostname=inbox.host, port=inbox.port, server_hostname="localhost"
    )
    controller.start()
    yield inbox
    controller.stop()


@pytest.fixture
def task_env(monkeypatch: pytest.MonkeyPatch, smtp_server: SmtpInbox) -> SmtpInbox:
    monkeypatch.setenv("NOTIFICATIONS_DB", TEST_DB)
    monkeypatch.setenv("SMTP_HOST", smtp_server.host)
    monkeypatch.setenv("SMTP_PORT", str(smtp_server.port))
    monkeypatch.setenv("RETRY_BASE_SECONDS", "0.01")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@shop.test")
    monkeypatch.setenv("REQUEUE_AFTER_SECONDS", "60")
    return smtp_server
