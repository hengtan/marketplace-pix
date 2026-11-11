from uuid import NAMESPACE_URL, UUID, uuid5

from assistant.domain.models import Passage


def pid(slug: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"marketplace-pix:product:{slug}")


def passage(
    slug: str = "fone",
    name: str = "Fone Nova",
    price_cents: int = 10000,
    rating: float = 4.5,
    content: str | None = None,
    category: str = "tecnologia",
    score: float = 0.5,
    index: int = 0,
) -> Passage:
    return Passage(
        chunk_id=f"{pid(slug)}:{index}",
        product_id=pid(slug),
        slug=slug,
        name=name,
        category=category,
        price_cents=price_cents,
        rating=rating,
        content=content or f"Produto: {name} | Categoria: {category}\nUm bom produto.",
        score=score,
    )
