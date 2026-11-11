import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.application.ports import ChunkStore
from assistant.application.retrieval import to_tsquery_terms
from assistant.domain.models import EmbeddedChunk, Filters, Passage

_COLUMNS = "id, product_id, content, metadata"


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.7f}" for v in vector) + "]"


def _where(embedder: str, filters: Filters) -> tuple[str, dict[str, Any]]:
    clauses = ["metadata->>'embedder' = :embedder"]
    params: dict[str, Any] = {"embedder": embedder}
    if filters.max_price_cents is not None:
        clauses.append("(metadata->>'price_cents')::int <= :max_price")
        params["max_price"] = filters.max_price_cents
    if filters.min_price_cents is not None:
        clauses.append("(metadata->>'price_cents')::int >= :min_price")
        params["min_price"] = filters.min_price_cents
    if filters.category is not None:
        clauses.append("metadata->>'category' = :category")
        params["category"] = filters.category
    if filters.min_rating is not None:
        clauses.append("(metadata->>'rating')::float >= :min_rating")
        params["min_rating"] = filters.min_rating
    if filters.product_ids is not None:
        clauses.append("product_id = ANY(:product_ids)")
        params["product_ids"] = list(filters.product_ids)
    return " AND ".join(clauses), params


def _passage(row: Any, score: float, source: str) -> Passage:
    meta = row.metadata
    return Passage(
        chunk_id=row.id,
        product_id=row.product_id,
        slug=meta["slug"],
        name=meta["name"],
        category=meta["category"],
        price_cents=int(meta["price_cents"]),
        rating=float(meta["rating"]),
        content=row.content,
        score=score,
        source=source,
    )


class PgChunkStore(ChunkStore):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def existing_hashes(self) -> dict[str, str]:
        async with self._factory() as session:
            rows = await session.execute(text("SELECT id, content_hash FROM chunks"))
            return {row.id: row.content_hash for row in rows}

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        if not chunks:
            return
        params = [
            {
                "id": c.draft.chunk_id,
                "product_id": c.draft.product_id,
                "chunk_index": c.draft.chunk_index,
                "content": c.draft.content,
                "content_hash": c.draft.content_hash,
                "embedding": vector_literal(c.embedding),
                "metadata": json.dumps(c.draft.metadata, ensure_ascii=False),
            }
            for c in chunks
        ]
        async with self._factory.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO chunks
                        (id, product_id, chunk_index, content, content_hash, embedding, metadata)
                    VALUES (:id, :product_id, :chunk_index, :content, :content_hash,
                            CAST(CAST(:embedding AS text) AS vector), CAST(:metadata AS jsonb))
                    ON CONFLICT (id) DO UPDATE SET
                        chunk_index = EXCLUDED.chunk_index,
                        content = EXCLUDED.content,
                        content_hash = EXCLUDED.content_hash,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata,
                        updated_at = now()
                    """
                ),
                params,
            )

    async def delete(self, chunk_ids: Sequence[str]) -> None:
        if not chunk_ids:
            return
        async with self._factory.begin() as session:
            await session.execute(
                text("DELETE FROM chunks WHERE id = ANY(:ids)"), {"ids": list(chunk_ids)}
            )

    async def vector_search(
        self, embedding: Sequence[float], embedder: str, filters: Filters, limit: int
    ) -> list[Passage]:
        where, params = _where(embedder, filters)
        sql = f"""
            SELECT {_COLUMNS}, 1 - (embedding <=> CAST(CAST(:v AS text) AS vector)) AS score
            FROM chunks WHERE {where}
            ORDER BY embedding <=> CAST(CAST(:v AS text) AS vector), id
            LIMIT :limit
        """
        async with self._factory() as session:
            rows = await session.execute(
                text(sql), {**params, "v": vector_literal(embedding), "limit": limit}
            )
            return [_passage(r, float(r.score), "vector") for r in rows]

    async def text_search(
        self, query: str, embedder: str, filters: Filters, limit: int
    ) -> list[Passage]:
        terms = to_tsquery_terms(query)
        if not terms:
            return []
        where, params = _where(embedder, filters)
        sql = f"""
            SELECT {_COLUMNS}, ts_rank_cd(tsv, q) AS score
            FROM chunks, to_tsquery('portuguese', f_unaccent(:q)) AS q
            WHERE tsv @@ q AND {where}
            ORDER BY score DESC, id
            LIMIT :limit
        """
        async with self._factory() as session:
            rows = await session.execute(text(sql), {**params, "q": terms, "limit": limit})
            return [_passage(r, float(r.score), "text") for r in rows]

    async def browse(
        self, embedder: str, filters: Filters, sort: str | None, limit: int
    ) -> list[Passage]:
        where, params = _where(embedder, filters)
        order = (
            "(metadata->>'price_cents')::int, (metadata->>'rating')::float DESC"
            if sort == "price_asc"
            else "(metadata->>'rating')::float DESC, (metadata->>'price_cents')::int"
        )
        sql = f"""
            SELECT {_COLUMNS}
            FROM chunks
            WHERE {where} AND chunk_index = 0
            ORDER BY {order}, id
            LIMIT :limit
        """
        async with self._factory() as session:
            rows = await session.execute(text(sql), {**params, "limit": limit})
            return [_passage(r, 0.0, "browse") for r in rows]

    async def categories(self, embedder: str) -> dict[str, str]:
        async with self._factory() as session:
            rows = await session.execute(
                text(
                    """
                    SELECT DISTINCT metadata->>'category' AS slug,
                           COALESCE(metadata->>'category_label', metadata->>'category') AS label
                    FROM chunks WHERE metadata->>'embedder' = :embedder
                    """
                ),
                {"embedder": embedder},
            )
            return {r.slug: r.label for r in rows}

    async def product_names(self, embedder: str) -> list[str]:
        async with self._factory() as session:
            rows = await session.execute(
                text(
                    "SELECT DISTINCT metadata->>'name' AS name FROM chunks "
                    "WHERE metadata->>'embedder' = :embedder"
                ),
                {"embedder": embedder},
            )
            return [r.name for r in rows]

    async def product_chunks(
        self, embedder: str, product_ids: Sequence[UUID] | None = None
    ) -> dict[UUID, list[str]]:
        clauses = "metadata->>'embedder' = :embedder"
        params: dict[str, Any] = {"embedder": embedder}
        if product_ids is not None:
            clauses += " AND product_id = ANY(:ids)"
            params["ids"] = list(product_ids)
        async with self._factory() as session:
            rows = await session.execute(
                text(
                    f"SELECT product_id, content FROM chunks WHERE {clauses} "
                    "ORDER BY product_id, chunk_index"
                ),
                params,
            )
            grouped: dict[UUID, list[str]] = {}
            for row in rows:
                grouped.setdefault(row.product_id, []).append(row.content)
            return grouped

    async def embeddings(self, chunk_ids: Sequence[str]) -> dict[str, list[float]]:
        if not chunk_ids:
            return {}
        async with self._factory() as session:
            rows = await session.execute(
                text("SELECT id, embedding::text AS vec FROM chunks WHERE id = ANY(:ids)"),
                {"ids": list(chunk_ids)},
            )
            return {r.id: [float(x) for x in r.vec.strip("[]").split(",")] for r in rows}
