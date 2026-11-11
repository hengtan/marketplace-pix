import logging
from typing import Any
from uuid import UUID

from marketplace_common.messaging.events import IncomingEvent

from assistant.application.ingest import IngestCatalog
from assistant.application.semantic_cache import SemanticCache
from assistant.metrics import CATALOG_EVENTS

logger = logging.getLogger(__name__)

CATALOG_TOPIC = "catalog.events"
PRODUCT_CHANGED = frozenset({"ProductCreated", "ProductUpdated", "ProductPriceChanged"})
PRODUCT_REMOVED = frozenset({"ProductDeleted"})


class CatalogEventHandler:
    """Keeps the index and the cache honest when the catalog changes: reindexes (only the
    changed chunks are embedded again) and drops cached answers that cite the product."""

    def __init__(self, ingest: IngestCatalog, cache: SemanticCache) -> None:
        self._ingest = ingest
        self._cache = cache

    async def handle(self, event: IncomingEvent) -> dict[str, Any]:
        if event.type not in PRODUCT_CHANGED | PRODUCT_REMOVED:
            CATALOG_EVENTS.labels(event.type, "ignored").inc()
            return {"ignored": True}
        report = await self._ingest.execute()
        product_id = _product_id(event)
        if product_id is None:
            removed = await self._cache.invalidate_all()
        else:
            removed = await self._cache.invalidate_products(
                [product_id], include_volatile=event.type in PRODUCT_CHANGED
            )
        CATALOG_EVENTS.labels(event.type, "handled").inc()
        logger.info(
            "catalog event type=%s reindexed=%d removed=%d cache_invalidated=%d",
            event.type,
            report.indexed,
            report.removed,
            removed,
        )
        return {"reindexed": report.indexed, "cache_invalidated": removed}


def _product_id(event: IncomingEvent) -> UUID | None:
    raw = event.payload.get("product_id") or event.key
    try:
        return UUID(str(raw))
    except ValueError:
        return None
