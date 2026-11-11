from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from marketplace_common.maintenance.policy import RetentionPolicy
from marketplace_common.observability.metrics import (
    CLEANUP_BATCHES,
    CLEANUP_DELETED,
    CLEANUP_DURATION,
    CLEANUP_LAST_SUCCESS,
    CLEANUP_RUNS,
)

logger = logging.getLogger(__name__)

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class CleanupTarget:
    """Linhas de `table` cuja coluna de tempo passou da retenção. A coluna nula nunca é apagada."""

    name: str
    table: str
    time_column: str
    retention_seconds: float

    def __post_init__(self) -> None:
        for identifier in (self.table, self.time_column):
            if not IDENTIFIER.match(identifier):
                raise ValueError(f"unsafe SQL identifier: {identifier!r}")
        if self.retention_seconds <= 0:
            raise ValueError("retention must be positive")


def outbox_target(policy: RetentionPolicy, table: str = "outbox_events") -> CleanupTarget:
    return CleanupTarget(
        "outbox_published", table, "published_at", policy.outbox_published.total_seconds()
    )


def inbox_target(policy: RetentionPolicy, table: str = "inbox_messages") -> CleanupTarget:
    return CleanupTarget("inbox", table, "processed_at", policy.inbox.total_seconds())


def idempotency_target(policy: RetentionPolicy, table: str = "idempotency_keys") -> CleanupTarget:
    return CleanupTarget(
        "idempotency_keys", table, "created_at", policy.idempotency_keys.total_seconds()
    )


def _delete_batch_sql(target: CleanupTarget) -> str:
    return (
        f"WITH doomed AS ("
        f" SELECT ctid FROM {target.table}"
        f" WHERE {target.time_column} < now() - make_interval(secs => :retention)"
        f" ORDER BY {target.time_column}"
        f" LIMIT :batch"
        f" FOR UPDATE SKIP LOCKED)"
        f" DELETE FROM {target.table}"
        f" WHERE ctid = ANY (ARRAY(SELECT ctid FROM doomed))"
    )


class CleanupJob:
    """Apaga linhas expiradas em lotes pequenos, cada um em uma transação curta.

    O lote usa `FOR UPDATE SKIP LOCKED`: linhas travadas por outra transação são puladas em vez de
    esperadas, e várias réplicas do job rodam juntas sem disputa. Nenhuma transação segura mais
    de `batch_size` linhas, então quem escreve na tabela quase não sente.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        targets: list[CleanupTarget],
        policy: RetentionPolicy | None = None,
    ) -> None:
        self._engine = engine
        self._targets = targets
        self._policy = policy or RetentionPolicy()

    async def run_once(self) -> dict[str, int]:
        started = time.perf_counter()
        deleted: dict[str, int] = {}
        for target in self._targets:
            deleted[target.name] = await self._clean(target)
        CLEANUP_DURATION.observe(time.perf_counter() - started)
        CLEANUP_LAST_SUCCESS.set_to_current_time()
        return deleted

    async def _clean(self, target: CleanupTarget) -> int:
        statement = text(_delete_batch_sql(target))
        total = 0
        for _ in range(self._policy.max_batches_per_run):
            async with self._engine.begin() as connection:
                result = await connection.execute(
                    statement,
                    {"retention": target.retention_seconds, "batch": self._policy.batch_size},
                )
            removed = int(result.rowcount)
            total += removed
            CLEANUP_BATCHES.labels(table=target.name).inc()
            if removed:
                CLEANUP_DELETED.labels(table=target.name).inc(removed)
            if removed < self._policy.batch_size:
                break
            await asyncio.sleep(self._policy.pause_seconds)
        return total

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                deleted = await self.run_once()
            except Exception:
                CLEANUP_RUNS.labels(result="error").inc()
                logger.exception("cleanup run failed, will retry on the next interval")
            else:
                CLEANUP_RUNS.labels(result="success").inc()
                if any(deleted.values()):
                    logger.info("cleanup removed %s", deleted)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._policy.interval_seconds)
