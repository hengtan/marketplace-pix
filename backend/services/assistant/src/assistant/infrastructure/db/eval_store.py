from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.application.ports import EvalRunRecord, EvalStore
from assistant.infrastructure.db.models import EvalRunRow


class PgEvalStore(EvalStore):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def save(self, record: EvalRunRecord) -> None:
        async with self._factory.begin() as session:
            session.add(
                EvalRunRow(
                    id=record.run_id,
                    created_at=record.created_at,
                    passed=record.passed,
                    embedder=record.embedder,
                    llm=record.llm,
                    cases_count=len(record.cases),
                    metrics=record.metrics,
                    thresholds=record.thresholds,
                    cases=record.cases,
                )
            )

    async def latest(self) -> EvalRunRecord | None:
        async with self._factory() as session:
            row = await session.scalar(
                select(EvalRunRow).order_by(EvalRunRow.created_at.desc()).limit(1)
            )
        if row is None:
            return None
        return EvalRunRecord(
            run_id=row.id,
            created_at=row.created_at,
            passed=row.passed,
            metrics=row.metrics,
            thresholds=row.thresholds,
            cases=row.cases,
            embedder=row.embedder,
            llm=row.llm,
        )
