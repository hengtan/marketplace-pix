import logging
from dataclasses import asdict, dataclass, replace

from assistant.application.documents import build_chunks
from assistant.application.ports import CatalogGateway, ChunkStore, Embedder
from assistant.application.prompt import REMOVED_MARK, sanitize_untrusted
from assistant.domain.chunking import RecursiveChunker
from assistant.domain.models import CatalogProduct, ChunkDraft, EmbeddedChunk

logger = logging.getLogger(__name__)

EMBED_BATCH = 32


@dataclass(frozen=True)
class IngestReport:
    indexed: int
    skipped: int
    removed: int
    flagged: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def sanitize_product(product: CatalogProduct) -> tuple[CatalogProduct, int]:
    """Third-party text (name, description, tags, merchant) is untrusted: sentences that look
    like instructions for a model are removed before the product is indexed."""
    total = 0
    name, flagged = sanitize_untrusted(product.name)
    total += flagged
    description, flagged = sanitize_untrusted(product.description)
    total += flagged
    merchant, flagged = sanitize_untrusted(product.merchant_name)
    total += flagged
    tags: list[str] = []
    for tag in product.tags:
        clean, flagged = sanitize_untrusted(tag)
        total += flagged
        if clean and REMOVED_MARK not in clean:
            tags.append(clean)
    if not total:
        return product, 0
    return (
        replace(
            product,
            name=name or product.name,
            description=description,
            merchant_name=merchant or product.merchant_name,
            tags=tuple(tags),
        ),
        total,
    )


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
        flagged = 0
        for raw in products:
            product, suspicious = sanitize_product(raw)
            if suspicious:
                flagged += 1
                logger.warning(
                    "product text neutralized product=%s sentences=%d", raw.id, suspicious
                )
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
            indexed=len(pending),
            skipped=len(drafts) - len(pending),
            removed=len(stale),
            flagged=flagged,
        )
        logger.info(
            "ingest finished indexed=%d skipped=%d removed=%d flagged=%d",
            report.indexed,
            report.skipped,
            report.removed,
            report.flagged,
        )
        return report
