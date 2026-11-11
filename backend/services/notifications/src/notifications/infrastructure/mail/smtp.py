from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import aiosmtplib

from notifications.application.errors import SendError
from notifications.application.ports import OutgoingEmail


def build_message(email: OutgoingEmail, sender_address: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender_address
    message["To"] = formataddr((email.to_name, email.to_email))
    message["Subject"] = email.subject
    message["Message-ID"] = make_msgid(domain="marketplace-pix.local")
    message.set_content(email.text)
    message.add_alternative(email.html, subtype="html")
    return message


class SmtpEmailSender:
    def __init__(self, host: str, port: int, sender_address: str, timeout: float = 10.0) -> None:
        self._host = host
        self._port = port
        self._sender_address = sender_address
        self._timeout = timeout

    async def send(self, email: OutgoingEmail) -> None:
        message = build_message(email, self._sender_address)
        try:
            await aiosmtplib.send(
                message, hostname=self._host, port=self._port, timeout=self._timeout
            )
        except (
            aiosmtplib.SMTPRecipientsRefused,
            aiosmtplib.SMTPSenderRefused,
            aiosmtplib.SMTPDataError,
        ) as exc:
            raise SendError(str(exc), permanent=_is_permanent(exc)) from exc


def _is_permanent(exc: Exception) -> bool:
    codes: list[object]
    if isinstance(exc, aiosmtplib.SMTPRecipientsRefused):
        codes = [r.code for r in exc.recipients]
    else:
        codes = [getattr(exc, "code", None)]
    return bool(codes) and all(isinstance(c, int) and 500 <= c < 600 for c in codes)
