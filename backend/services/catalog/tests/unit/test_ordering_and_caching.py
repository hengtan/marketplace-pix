import httpx
import pytest
from sqlalchemy.dialects import postgresql

from catalog.domain.sorting import SortOrder
from catalog.infrastructure.db.repository import order_clauses
from catalog.interface.api import create_app
from catalog.interface.caching import compute_etag, matches


def _sql(sort: SortOrder, search: str | None = None) -> list[str]:
    return [
        str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        for clause in order_clauses(sort, search)
    ]


@pytest.mark.parametrize(
    ("sort", "expected_first"),
    [
        (SortOrder.PRICE_ASC, "products.price_cents ASC"),
        (SortOrder.PRICE_DESC, "products.price_cents DESC"),
        (SortOrder.NEWEST, "products.created_at DESC"),
        (SortOrder.RATING, "products.rating DESC"),
        (SortOrder.RELEVANCE, "products.reviews_count DESC"),
    ],
)
def test_sort_order_maps_to_expected_primary_clause(sort: SortOrder, expected_first: str) -> None:
    assert _sql(sort)[0] == expected_first


def test_every_sort_has_deterministic_tiebreak() -> None:
    for sort in SortOrder:
        assert _sql(sort)[-2:] == ["products.name ASC", "products.id ASC"]


def test_relevance_with_search_orders_by_trigram_score_first() -> None:
    first = _sql(SortOrder.RELEVANCE, "luminaria")[0]
    assert "word_similarity" in first
    assert first.index("name_search") < first.index("description_search")
    assert first.index("description_search") < first.index("tags_search")
    assert first.endswith("DESC")


def test_etag_is_stable_and_quoted() -> None:
    assert compute_etag(b"abc") == compute_etag(b"abc")
    assert compute_etag(b"abc") != compute_etag(b"abd")
    assert compute_etag(b"abc").startswith('"')


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, False),
        ("", False),
        ('"x"', True),
        ('W/"x"', True),
        ('"a", "x"', True),
        ("*", True),
        ('"y"', False),
    ],
)
def test_if_none_match_matching(header: str | None, expected: bool) -> None:
    assert matches(header, '"x"') is expected


async def test_ready_returns_503_when_check_fails() -> None:
    async def failing() -> bool:
        return False

    app = create_app(ready_check=failing)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        response = await c.get("/ready")
        assert response.status_code == 503
        assert (await c.get("/health")).status_code == 200


def test_reads_revalidate_by_default_so_a_merchant_edit_is_never_served_stale() -> None:
    from catalog.config import Settings
    from catalog.interface.caching import cached_json

    assert Settings.model_fields["cache_max_age_seconds"].default == 0

    from fastapi import FastAPI
    from pydantic import BaseModel
    from starlette.requests import Request

    class Item(BaseModel):
        name: str

    app = FastAPI()
    app.state.cache_max_age = 0
    request = Request({"type": "http", "headers": [], "app": app, "method": "GET", "path": "/"})
    response = cached_json(request, Item(name="x"))
    assert response.headers["cache-control"] == "public, max-age=0, must-revalidate"
    assert response.headers["etag"]


def test_a_positive_ttl_keeps_the_plain_max_age_form() -> None:
    from fastapi import FastAPI
    from pydantic import BaseModel
    from starlette.requests import Request

    from catalog.interface.caching import cached_json

    class Item(BaseModel):
        name: str

    app = FastAPI()
    app.state.cache_max_age = 60
    request = Request({"type": "http", "headers": [], "app": app, "method": "GET", "path": "/"})
    assert cached_json(request, Item(name="x")).headers["cache-control"] == "public, max-age=60"
