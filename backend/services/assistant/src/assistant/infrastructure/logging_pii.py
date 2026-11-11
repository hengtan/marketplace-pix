import logging

from assistant.domain.pii import redact


def install_pii_redaction() -> None:
    """Redacts personal data from every log record at creation time, so no handler or formatter
    downstream (console, JSON, collector) ever sees it."""
    previous = logging.getLogRecordFactory()
    if getattr(previous, "pii_safe", False):
        return

    def factory(*args: object, **kwargs: object) -> logging.LogRecord:
        record = previous(*args, **kwargs)  # type: ignore[arg-type,unused-ignore]
        try:
            message = record.getMessage()
        except Exception:
            return record
        clean = redact(message)
        if clean != message:
            record.msg = clean
            record.args = ()
        return record

    factory.pii_safe = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
