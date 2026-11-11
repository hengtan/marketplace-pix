from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from catalog.domain.errors import InvalidQuery
from catalog.domain.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageRequest
from catalog.domain.product import Merchant, Product, ProductQuery, normalize_search_text
from catalog.domain.sorting import SortOrder


def make_product(**overrides: object) -> Product:
    values: dict[str, object] = {
        "id": uuid4(),
        "slug": "luminaria",
        "name": "Luminária",
        "description": "Luz quente",
        "price_cents": 1000,
        "currency": "BRL",
        "category": "casa",
        "image_url": None,
        "rating": Decimal("4.5"),
        "reviews_count": 10,
        "tags": ("luz",),
        "merchant": Merchant(id=uuid4(), slug="casa-lume", name="Casa Lume"),
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return Product(**values)  # type: ignore[arg-type]


def test_page_request_defaults() -> None:
    page = PageRequest()
    assert page.page == 1
    assert page.page_size == DEFAULT_PAGE_SIZE == 12
    assert page.offset == 0


def test_page_request_offset() -> None:
    assert PageRequest(page=3, page_size=10).offset == 20


@pytest.mark.parametrize(
    ("page", "page_size"),
    [(0, 12), (-1, 12), (1, 0), (1, MAX_PAGE_SIZE + 1)],
)
def test_page_request_rejects_invalid_values(page: int, page_size: int) -> None:
    with pytest.raises(InvalidQuery):
        PageRequest(page=page, page_size=page_size)


def test_page_request_accepts_maximum_page_size() -> None:
    assert PageRequest(page_size=48).page_size == 48


def test_sort_order_values_match_contract() -> None:
    assert {s.value for s in SortOrder} == {
        "relevance",
        "price_asc",
        "price_desc",
        "newest",
        "rating",
    }


def test_normalize_search_text_removes_accents_case_and_extra_spaces() -> None:
    assert normalize_search_text("  Luminária   ARCO  ") == "luminaria arco"
    assert normalize_search_text("Tênis de Corrida") == "tenis de corrida"


def test_query_blank_search_is_ignored() -> None:
    assert ProductQuery(search="   ").normalized_search is None
    assert ProductQuery().normalized_search is None


def test_query_rejects_inverted_price_range() -> None:
    with pytest.raises(InvalidQuery):
        ProductQuery(min_price_cents=2000, max_price_cents=1000)


def test_query_rejects_negative_price() -> None:
    with pytest.raises(InvalidQuery):
        ProductQuery(min_price_cents=-1)


def test_query_rejects_overlong_search() -> None:
    with pytest.raises(InvalidQuery):
        ProductQuery(search="a" * 101)


def test_query_accepts_equal_bounds() -> None:
    query = ProductQuery(min_price_cents=1000, max_price_cents=1000)
    assert query.min_price_cents == query.max_price_cents


def test_product_rejects_non_positive_price() -> None:
    with pytest.raises(ValueError):
        make_product(price_cents=0)


@pytest.mark.parametrize("rating", [Decimal("-0.1"), Decimal("5.1")])
def test_product_rejects_rating_out_of_range(rating: Decimal) -> None:
    with pytest.raises(ValueError):
        make_product(rating=rating)


def test_product_rejects_negative_reviews() -> None:
    with pytest.raises(ValueError):
        make_product(reviews_count=-1)


def test_valid_product_is_built() -> None:
    assert make_product().rating == Decimal("4.5")
