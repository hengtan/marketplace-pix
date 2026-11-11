import hashlib
import json
from typing import Any
from uuid import UUID

from assistant.domain.chunking import RecursiveChunker
from assistant.domain.models import CatalogProduct, ChunkDraft
from assistant.domain.text import format_brl


def build_document(product: CatalogProduct) -> str:
    details = [
        f"Preço: {format_brl(product.price_cents)}.",
        f"Avaliação: {product.rating:.1f} de 5 em {product.reviews_count} avaliações.",
        f"Vendido por {product.merchant_name}.",
    ]
    if product.tags:
        details.append(f"Palavras-chave: {', '.join(product.tags)}.")
    return f"{product.description.strip()}\n{' '.join(details)}"


def contextual_header(product: CatalogProduct, category_label: str) -> str:
    return f"Produto: {product.name} | Categoria: {category_label}"


def content_hash(embedder: str, content: str, metadata: dict[str, Any]) -> str:
    canonical = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
    payload = f"{embedder}\x00{content}\x00{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chunk_id(product_id: UUID, index: int) -> str:
    return f"{product_id}:{index}"


def build_chunks(
    product: CatalogProduct,
    chunker: RecursiveChunker,
    embedder_name: str,
    category_label: str | None = None,
) -> list[ChunkDraft]:
    label = category_label or product.category
    bodies = chunker.split(build_document(product))
    header = contextual_header(product, label)
    drafts: list[ChunkDraft] = []
    for index, body in enumerate(bodies):
        content = f"{header}\n{body}"
        metadata: dict[str, Any] = {
            "product_id": str(product.id),
            "slug": product.slug,
            "name": product.name,
            "category": product.category,
            "category_label": label,
            "price_cents": product.price_cents,
            "rating": product.rating,
            "chunk_index": index,
            "chunks_total": len(bodies),
            "embedder": embedder_name,
        }
        drafts.append(
            ChunkDraft(
                chunk_id=chunk_id(product.id, index),
                product_id=product.id,
                chunk_index=index,
                content=content,
                content_hash=content_hash(embedder_name, content, metadata),
                metadata=metadata,
            )
        )
    return drafts
