import hashlib
from dataclasses import replace
from uuid import UUID

from assistant.application.rerank import LexicalReranker
from assistant.application.retrieval import HybridRetriever, RetrievalConfig
from assistant.domain.models import EmbeddedChunk
from tests.memory_store import build_store


async def _scaled_store(clones: int):  # type: ignore[no-untyped-def]
    store, embedder = await build_store()
    originals = list(store.chunks.values())
    for n in range(clones):
        for chunk in originals:
            if chunk.draft.metadata["slug"] != "fone-bluetooth-nova":
                continue
            digest = hashlib.sha256(f"{chunk.draft.chunk_id}:{n}".encode()).hexdigest()
            product = UUID(digest[:32])
            price = 5000 + (int(digest[32:40], 16) % 40000)
            meta = {
                **chunk.draft.metadata,
                "product_id": str(product),
                "slug": f"fone-clone-{n}",
                "price_cents": price,
            }
            draft = replace(
                chunk.draft,
                chunk_id=f"{product}:{chunk.draft.chunk_index}",
                product_id=product,
                metadata=meta,
            )
            store.chunks[draft.chunk_id] = EmbeddedChunk(draft, chunk.embedding)
    return store, embedder


async def test_prefilter_returns_full_results_where_postfilter_starves() -> None:
    store, embedder = await _scaled_store(200)
    question = "fone bluetooth com cancelamento de ruido ate 100 reais"
    cfg = RetrievalConfig(branch_limit=20, candidates=10, final=4)
    pre = await HybridRetriever(store, embedder, LexicalReranker(), cfg).retrieve(question)
    post = await HybridRetriever(
        store, embedder, LexicalReranker(), replace(cfg, prefilter=False)
    ).retrieve(question)
    assert len(pre.passages) == 4
    assert all(p.price_cents <= 10000 for p in pre.passages)
    assert len(post.passages) < len(pre.passages)
