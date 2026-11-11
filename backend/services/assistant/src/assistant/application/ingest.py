import logging
from dataclasses import asdict, dataclass

from assistant.application.documents import build_chunks
from assistant.application.ports import CatalogGateway, ChunkStore, Embedder
from assistant.domain.chunking import RecursiveChunker
from assistant.domain.models import ChunkDraft, EmbeddedChunk

logger = logging.getLogger(__name__)

EMBED_BATCH = 32


@dataclass(frozen=True)
class IngestReport:
    indexed: int
    skipped: int
    removed: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class IngestCatalog:
    def __init__(
        self,
        catalog: CatalogGateway,
        store: ChunkStore,
        embedder: Embedder,
        chunker: RecursiveChunker,
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._embedder = embedder
        self._chunker = chunker

    async def execute(self) -> IngestReport:
        products = await self._catalog.list_products()
        labels = await self._catalog.categories()
        drafts: list[ChunkDraft] = []
        for product in products:
            drafts.extend(
                build_chunks(
                    product, self._chunker, self._embedder.name, labels.get(product.category)
                )
            )

        existing = await self._store.existing_hashes()
        wanted = {draft.chunk_id for draft in drafts}
        pending = [d for d in drafts if existing.get(d.chunk_id) != d.content_hash]
        stale = [chunk_id for chunk_id in existing if chunk_id not in wanted]

        for start in range(0, len(pending), EMBED_BATCH):
            batch = pending[start : start + EMBED_BATCH]
            vectors = await self._embedder.embed([d.content for d in batch])
            await self._store.upsert(
                [EmbeddedChunk(draft, vec) for draft, vec in zip(batch, vectors, strict=True)]
            )
        if stale:
            await self._store.delete(stale)

        report = IngestReport(
            indexed=len(pending), skipped=len(drafts) - len(pending), removed=len(stale)
        )
        logger.info(
            "ingest finished indexed=%d skipped=%d removed=%d",
            report.indexed,
            report.skipped,
            report.removed,
        )
        return report
