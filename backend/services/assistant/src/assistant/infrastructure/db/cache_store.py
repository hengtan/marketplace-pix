import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.application.semantic_cache import CacheEntry, CacheHit, CacheStore, CacheSummary
from assistant.infrastructure.db.chunk_store import vector_literal


class PgCacheStore(CacheStore):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def lookup(
        self, embedding: list[float], embedder: str, filter_key: str, threshold: float
    ) -> CacheHit | None:
        sql = text(
            """
            SELECT id, payload, query_text, tokens_saved,
                   1 - (embedding <=> CAST(CAST(:v AS text) AS vector)) AS similarity
            FROM semantic_cache
            WHERE embedder = :embedder AND filter_key = :key AND expires_at > now()
            ORDER BY embedding <=> CAST(CAST(:v AS text) AS vector)
            LIMIT 1
            """
        )
        async with self._factory.begin() as session:
            row = (
                await session.execute(
                    sql, {"v": vector_literal(embedding), "embedder": embedder, "key": filter_key}
                )
            ).first()
            if row is None or float(row.similarity) < threshold:
                return None
            await session.execute(
                text("UPDATE semantic_cache SET hits = hits + 1 WHERE id = :id"), {"id": row.id}
            )
            return CacheHit(row.payload, float(row.similarity), row.tokens_saved, row.query_text)

    async def put(self, entry: CacheEntry) -> None:
        async with self._factory.begin() as session:
            await session.execute(
                text(
                    "DELETE FROM semantic_cache WHERE embedder = :e AND filter_key = :k "
                    "AND 1 - (embedding <=> CAST(CAST(:v AS text) AS vector)) >= 0.999"
                ),
                {
                    "e": entry.embedder,
                    "k": entry.filter_key,
                    "v": vector_literal(entry.embedding),
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO semantic_cache
                        (embedder, filter_key, intent, query_text, embedding, payload,
                         product_ids, volatile, tokens_saved, expires_at)
                    VALUES (:embedder, :key, :intent, :query,
                            CAST(CAST(:v AS text) AS vector), CAST(:payload AS jsonb),
                            :products, :volatile, :tokens,
                            now() + make_interval(secs => :ttl))
                    """
                ),
                {
                    "embedder": entry.embedder,
                    "key": entry.filter_key,
                    "intent": entry.intent,
                    "query": entry.query_text,
                    "v": vector_literal(entry.embedding),
                    "payload": json.dumps(entry.payload, ensure_ascii=False),
                    "products": list(entry.product_ids),
                    "volatile": entry.volatile,
                    "tokens": entry.tokens_saved,
                    "ttl": entry.ttl_seconds,
                },
            )

    async def invalidate_products(self, product_ids: list[UUID], include_volatile: bool) -> int:
        sql = "DELETE FROM semantic_cache WHERE product_ids && CAST(:ids AS uuid[])"
        if include_volatile:
            sql += " OR volatile"
        async with self._factory.begin() as session:
            result = await session.execute(text(sql), {"ids": list(product_ids)})
            return int(getattr(result, "rowcount", 0) or 0)

    async def invalidate_all(self) -> int:
        async with self._factory.begin() as session:
            result = await session.execute(text("DELETE FROM semantic_cache"))
            return int(getattr(result, "rowcount", 0) or 0)

    async def purge_expired(self) -> int:
        async with self._factory.begin() as session:
            result = await session.execute(
                text("DELETE FROM semantic_cache WHERE expires_at <= now()")
            )
            return int(getattr(result, "rowcount", 0) or 0)

    async def summary(self) -> CacheSummary:
        async with self._factory() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT count(*) AS entries, COALESCE(sum(hits), 0) AS hits, "
                        "COALESCE(sum(hits::bigint * tokens_saved), 0) AS saved "
                        "FROM semantic_cache WHERE expires_at > now()"
                    )
                )
            ).one()
            return CacheSummary(int(row.entries), int(row.hits), int(row.saved))
