from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.application.budget import Usage


class PgUsageStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def get(self, scope: str, key: str, window: str) -> Usage:
        async with self._factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT tokens, cost_micro_usd FROM llm_usage "
                        "WHERE scope = :scope AND key = :key AND period = :window"
                    ),
                    {"scope": scope, "key": key, "window": window},
                )
            ).first()
        return Usage(int(row.tokens), int(row.cost_micro_usd)) if row else Usage()

    async def add(self, scope: str, key: str, window: str, tokens: int, cost_micro: int) -> None:
        async with self._factory.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO llm_usage (scope, key, period, tokens, cost_micro_usd)
                    VALUES (:scope, :key, :window, :tokens, :cost)
                    ON CONFLICT (scope, key, period) DO UPDATE SET
                        tokens = llm_usage.tokens + EXCLUDED.tokens,
                        cost_micro_usd = llm_usage.cost_micro_usd + EXCLUDED.cost_micro_usd,
                        updated_at = now()
                    """
                ),
                {
                    "scope": scope,
                    "key": key,
                    "window": window,
                    "tokens": tokens,
                    "cost": cost_micro,
                },
            )
