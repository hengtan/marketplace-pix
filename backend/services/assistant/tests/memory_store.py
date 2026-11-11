import math
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from assistant.application.documents import build_chunks
from assistant.domain.chunking import RecursiveChunker
from assistant.domain.models import EmbeddedChunk, Filters, Passage
from assistant.domain.text import content_tokens, stem
from assistant.infrastructure.embedders.hashing import HashingEmbedder
from assistant.infrastructure.fixtures import SnapshotCatalogGateway

SNAPSHOT = Path(__file__).parent / "fixtures" / "catalog.json"


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class InMemoryChunkStore:
    def __init__(self) -> None:
        self.chunks: dict[str, EmbeddedChunk] = {}

    async def existing_hashes(self) -> dict[str, str]:
        return {k: c.draft.content_hash for k, c in self.chunks.items()}

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        for chunk in chunks:
            self.chunks[chunk.draft.chunk_id] = chunk

    async def delete(self, chunk_ids: Sequence[str]) -> None:
        for chunk_id in chunk_ids:
            self.chunks.pop(chunk_id, None)

    def _eligible(self, embedder: str, filters: Filters) -> list[EmbeddedChunk]:
        out = []
        for chunk in self.chunks.values():
            meta = chunk.draft.metadata
            if meta["embedder"] != embedder:
                continue
            if filters.matches(
                int(meta["price_cents"]),
                meta["category"],
                float(meta["rating"]),
                chunk.draft.product_id,
            ):
                out.append(chunk)
        return out

    @staticmethod
    def _passage(chunk: EmbeddedChunk, score: float, source: str) -> Passage:
        meta = chunk.draft.metadata
        return Passage(
            chunk.draft.chunk_id,
            chunk.draft.product_id,
            meta["slug"],
            meta["name"],
            meta["category"],
            int(meta["price_cents"]),
            float(meta["rating"]),
            chunk.draft.content,
            score,
            source,
        )

    async def vector_search(
        self, embedding: Sequence[float], embedder: str, filters: Filters, limit: int
    ) -> list[Passage]:
        scored = [(_cosine(embedding, c.embedding), c) for c in self._eligible(embedder, filters)]
        scored.sort(key=lambda item: (-item[0], item[1].draft.chunk_id))
        return [self._passage(c, s, "vector") for s, c in scored[:limit]]

    async def text_search(
        self, query: str, embedder: str, filters: Filters, limit: int
    ) -> list[Passage]:
        wanted = {stem(t) for t in content_tokens(query)}
        scored = []
        for chunk in self._eligible(embedder, filters):
            have = {stem(t) for t in content_tokens(chunk.draft.content)}
            hits = len(wanted & have)
            if hits:
                scored.append((hits / math.sqrt(len(have)), chunk))
        scored.sort(key=lambda item: (-item[0], item[1].draft.chunk_id))
        return [self._passage(c, s, "text") for s, c in scored[:limit]]

    async def browse(
        self, embedder: str, filters: Filters, sort: str | None, limit: int
    ) -> list[Passage]:
        rows = [c for c in self._eligible(embedder, filters) if c.draft.chunk_index == 0]
        if sort == "price_asc":
            rows.sort(key=lambda c: (c.draft.metadata["price_cents"], -c.draft.metadata["rating"]))
        else:
            rows.sort(key=lambda c: (-c.draft.metadata["rating"], c.draft.metadata["price_cents"]))
        return [self._passage(c, 0.0, "browse") for c in rows[:limit]]

    async def categories(self, embedder: str) -> dict[str, str]:
        return {
            c.draft.metadata["category"]: c.draft.metadata["category_label"]
            for c in self.chunks.values()
            if c.draft.metadata["embedder"] == embedder
        }

    async def product_names(self, embedder: str) -> list[str]:
        return sorted({c.draft.metadata["name"] for c in self.chunks.values()})

    async def product_chunks(
        self, embedder: str, product_ids: Sequence[UUID] | None = None
    ) -> dict[UUID, list[str]]:
        grouped: dict[UUID, list[tuple[int, str]]] = {}
        for c in self.chunks.values():
            if c.draft.metadata["embedder"] != embedder:
                continue
            if product_ids is not None and c.draft.product_id not in product_ids:
                continue
            grouped.setdefault(c.draft.product_id, []).append(
                (c.draft.chunk_index, c.draft.content)
            )
        return {k: [text for _, text in sorted(v)] for k, v in grouped.items()}

    async def embeddings(self, chunk_ids: Sequence[str]) -> dict[str, list[float]]:
        return {i: self.chunks[i].embedding for i in chunk_ids if i in self.chunks}


async def build_store(
    embedder: HashingEmbedder | None = None, chunker: RecursiveChunker | None = None
) -> tuple[InMemoryChunkStore, HashingEmbedder]:
    embedder = embedder or HashingEmbedder(256)
    chunker = chunker or RecursiveChunker(300, 60)
    catalog = SnapshotCatalogGateway(SNAPSHOT)
    store = InMemoryChunkStore()
    for product in await catalog.list_products():
        drafts = build_chunks(product, chunker, embedder.name, catalog.labels[product.category])
        vectors = await embedder.embed([d.content for d in drafts])
        await store.upsert([EmbeddedChunk(d, v) for d, v in zip(drafts, vectors, strict=True)])
    return store, embedder
