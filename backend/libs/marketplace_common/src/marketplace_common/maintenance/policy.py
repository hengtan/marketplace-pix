from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Quanto manter cada tipo de linha de apoio, configurável por variável de ambiente.

    O inbox deve durar mais que a retenção do tópico no Kafka: apagar o registro de dedup
    enquanto a mensagem ainda pode ser reentregue reabre a porta para duplicidade.
    """

    outbox_published: timedelta = timedelta(days=7)
    inbox: timedelta = timedelta(days=14)
    idempotency_keys: timedelta = timedelta(hours=48)
    interval_seconds: float = 300.0
    batch_size: int = 1000
    max_batches_per_run: int = 50
    pause_seconds: float = 0.05

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RetentionPolicy:
        source = os.environ if env is None else env
        defaults = cls()

        def hours(name: str, default: timedelta) -> timedelta:
            raw = source.get(name)
            return timedelta(hours=float(raw)) if raw else default

        def number(name: str, default: float) -> float:
            raw = source.get(name)
            return float(raw) if raw else default

        return cls(
            outbox_published=hours("RETENTION_OUTBOX_PUBLISHED_HOURS", defaults.outbox_published),
            inbox=hours("RETENTION_INBOX_HOURS", defaults.inbox),
            idempotency_keys=hours("RETENTION_IDEMPOTENCY_HOURS", defaults.idempotency_keys),
            interval_seconds=number("CLEANUP_INTERVAL_SECONDS", defaults.interval_seconds),
            batch_size=int(number("CLEANUP_BATCH_SIZE", defaults.batch_size)),
            max_batches_per_run=int(number("CLEANUP_MAX_BATCHES", defaults.max_batches_per_run)),
            pause_seconds=number("CLEANUP_PAUSE_SECONDS", defaults.pause_seconds),
        )
