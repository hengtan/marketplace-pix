from dataclasses import replace

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from assistant.application.documents import build_chunks
from assistant.domain.chunking import RecursiveChunker
from assistant.domain.models import Filters
from assistant.infrastructure.db.chunk_store import PgChunkStore
from assistant.infrastructure.db.session import build_session_factory
from assistant.wiring import Container


def expected_chunks(container, products) -> int:  # type: ignore[no-untyped-def]
    chunker = RecursiveChunker(container.settings.chunk_size, container.settings.chunk_overlap)
    return sum(len(build_chunks(p, chunker, container.embedder.name)) for p in products)


async def scalar(engine: AsyncEngine, sql: str):  # type: ignore[no-untyped-def]
    async with engine.connect() as conn:
        return await conn.scalar(text(sql))


async def test_first_ingest_indexes_every_chunk(container, engine, snapshot_products) -> None:
    report = await container.ingest.execute()
    total = expected_chunks(container, snapshot_products)
    assert total > len(snapshot_products), "descriptions are long enough to produce several chunks"
    assert (report.indexed, report.skipped, report.removed) == (total, 0, 0)
    assert await scalar(engine, "select count(*) from chunks") == total


async def test_chunks_carry_contextual_header_and_metadata(container, engine) -> None:
    await container.ingest.execute()
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "select content, metadata, vector_dims(embedding) as dims from chunks "
                    "where metadata->>'slug' = 'cafeteira-prensa-francesa' and chunk_index = 0"
                )
            )
        ).one()
    assert row.content.startswith(
        "Produto: Cafeteira Prensa Francesa | Categoria: Casa e decoração\n"
    )
    assert row.dims == 256
    meta = row.metadata
    assert meta["category"] == "casa" and meta["price_cents"] == 14990
    assert meta["embedder"] == "hashing-256" and meta["slug"] == "cafeteira-prensa-francesa"


async def test_second_ingest_is_idempotent(container) -> None:
    first = await container.ingest.execute()
    second = await container.ingest.execute()
    assert (second.indexed, second.removed) == (0, 0)
    assert second.skipped == first.indexed


async def test_changed_product_reindexes_only_its_chunks(container, catalog) -> None:
    await container.ingest.execute()
    target = next(p for p in catalog.products if p.slug == "mouse-glide-pro")
    catalog.products = [
        replace(p, price_cents=15990) if p.id == target.id else p for p in catalog.products
    ]
    chunker = RecursiveChunker(container.settings.chunk_size, container.settings.chunk_overlap)
    own = len(build_chunks(target, chunker, container.embedder.name))
    report = await container.ingest.execute()
    assert report.indexed == own and report.removed == 0 and report.skipped > 0


async def test_product_removed_from_catalog_is_removed_from_index(
    container, catalog, engine
) -> None:
    await container.ingest.execute()
    gone = next(p for p in catalog.products if p.slug == "vaso-ceramica-terra")
    chunker = RecursiveChunker(container.settings.chunk_size, container.settings.chunk_overlap)
    own = len(build_chunks(gone, chunker, container.embedder.name))
    catalog.products = [p for p in catalog.products if p.id != gone.id]
    report = await container.ingest.execute()
    assert (report.indexed, report.removed) == (0, own)
    remaining = await scalar(engine, f"select count(*) from chunks where product_id = '{gone.id}'")
    assert remaining == 0


async def test_vector_search_orders_by_cosine_similarity(indexed: Container, engine) -> None:
    store = PgChunkStore(build_session_factory(engine))
    embedder = indexed.embedder
    query = (await embedder.embed(["fone bluetooth cancelamento ruido"]))[0]
    hits = await store.vector_search(query, embedder.name, Filters(), 10)
    assert hits[0].slug == "fone-bluetooth-nova"
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    exact = {
        h.chunk_id: sum(
            a * b for a, b in zip(query, (await embedder.embed([h.content]))[0], strict=True)
        )
        for h in hits
    }
    for hit in hits:
        assert abs(hit.score - exact[hit.chunk_id]) < 1e-4


async def test_vector_query_uses_the_hnsw_index(indexed: Container, engine) -> None:
    query = (await indexed.embedder.embed(["fone"]))[0]
    literal = "[" + ",".join(f"{v:.6f}" for v in query) + "]"
    async with engine.connect() as conn:
        await conn.execute(text("set enable_seqscan = off"))
        plan = (
            (
                await conn.execute(
                    text(
                        "explain select id from chunks "
                        "order by embedding <=> CAST(:v AS vector) limit 5"
                    ),
                    {"v": literal},
                )
            )
            .scalars()
            .all()
        )
    assert any("ix_chunks_embedding_hnsw" in line for line in plan), plan


async def test_text_search_uses_portuguese_config_and_ignores_accents(
    indexed: Container, engine
) -> None:
    store = PgChunkStore(build_session_factory(engine))
    name = indexed.embedder.name
    by_unaccented = await store.text_search("ruido", name, Filters(), 10)
    assert "fone-bluetooth-nova" in {h.slug for h in by_unaccented}
    by_stem = await store.text_search("correr", name, Filters(), 10)
    assert "tenis-corrida-vento" in {h.slug for h in by_stem}


async def test_filters_apply_to_both_searches(indexed: Container, engine) -> None:
    store = PgChunkStore(build_session_factory(engine))
    name = indexed.embedder.name
    vector = (await indexed.embedder.embed(["treino"]))[0]
    cheap = Filters(max_price_cents=10000, category="esporte")
    for hits in (
        await store.vector_search(vector, name, cheap, 20),
        await store.text_search("treino", name, cheap, 20),
        await store.browse(name, cheap, "price_asc", 20),
    ):
        assert hits
        assert all(h.price_cents <= 10000 and h.category == "esporte" for h in hits)


async def test_embedder_name_isolates_vectors(indexed: Container, engine) -> None:
    store = PgChunkStore(build_session_factory(engine))
    vector = (await indexed.embedder.embed(["fone"]))[0]
    assert await store.vector_search(vector, "other-embedder", Filters(), 5) == []


async def test_hybrid_retrieval_finds_and_ranks_the_right_product(indexed: Container) -> None:
    result = await indexed.retriever.retrieve("quero um fone com cancelamento de ruído")
    assert result.passages[0].slug == "fone-bluetooth-nova"
    assert len(result.passages) <= indexed.settings.retrieval_final
    assert len({p.product_id for p in result.passages}) == len(result.passages)
    assert result.mode == "hybrid"


async def test_hybrid_retrieval_applies_price_and_category_filters(indexed: Container) -> None:
    result = await indexed.retriever.retrieve("até R$ 100 o que tem?")
    assert result.filters.max_price_cents == 10000
    assert result.mode == "browse"
    assert result.passages and all(p.price_cents <= 10000 for p in result.passages)

    esporte = await indexed.retriever.retrieve("o mais barato de esporte")
    assert esporte.filters.category == "esporte"
    assert esporte.passages[0].slug == "corda-pular-speed"
    assert [p.price_cents for p in esporte.passages] == sorted(
        p.price_cents for p in esporte.passages
    )


async def test_out_of_scope_question_retrieves_nothing(indexed: Container) -> None:
    for question in ("qual a capital da França?", "quem ganhou a copa do mundo"):
        assert (await indexed.retriever.retrieve(question)).passages == []
