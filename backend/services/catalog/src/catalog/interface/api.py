from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from catalog.application.ports import ReaderFactory
from catalog.application.queries import (
    GetProduct,
    GetProductsByIds,
    ListCategories,
    SearchProducts,
)
from catalog.domain.errors import InvalidQuery, ProductNotFound
from catalog.domain.pagination import DEFAULT_PAGE_SIZE, PageRequest
from catalog.domain.product import ProductQuery
from catalog.domain.sorting import SortOrder
from catalog.interface.caching import cached_json
from catalog.interface.schemas import CategoryOut, ProductOut, ProductPageOut

ReadyCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def _parse_ids(raw: str) -> list[UUID]:
    try:
        return [UUID(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise InvalidQuery("ids must be a comma separated list of uuids") from None


def _reader_factory(request: Request) -> ReaderFactory:
    factory: ReaderFactory = request.app.state.reader_factory
    return factory


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/products")
    async def list_products(
        request: Request,
        q: str | None = None,
        category: str | None = None,
        min_price_cents: int | None = None,
        max_price_cents: int | None = None,
        sort: SortOrder = SortOrder.RELEVANCE,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Response:
        query = ProductQuery(
            search=q,
            category=category,
            min_price_cents=min_price_cents,
            max_price_cents=max_price_cents,
            sort=sort,
            page=PageRequest(page=page, page_size=page_size),
        )
        result = await SearchProducts(_reader_factory(request)).execute(query)
        return cached_json(request, ProductPageOut.from_domain(result))

    @router.get("/products/by-ids")
    async def products_by_ids(request: Request, ids: str = "") -> Response:
        products = await GetProductsByIds(_reader_factory(request)).execute(_parse_ids(ids))
        return cached_json(request, ProductPageOut.from_products(products))

    @router.get("/products/slug/{slug}")
    async def product_by_slug(slug: str, request: Request) -> Response:
        product = await GetProduct(_reader_factory(request)).by_slug(slug)
        return cached_json(request, ProductOut.from_domain(product))

    @router.get("/products/{product_id}")
    async def product_by_id(product_id: UUID, request: Request) -> Response:
        product = await GetProduct(_reader_factory(request)).by_id(product_id)
        return cached_json(request, ProductOut.from_domain(product))

    @router.get("/categories")
    async def categories(request: Request) -> Response:
        items = await ListCategories(_reader_factory(request)).execute()
        return cached_json(request, [CategoryOut.from_domain(c) for c in items])

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        check: ReadyCheck | None = getattr(request.app.state, "ready_check", None)
        ok = True if check is None else await check()
        return JSONResponse({"ready": ok}, status_code=200 if ok else 503)

    return router


def create_app(
    *,
    reader_factory: ReaderFactory | None = None,
    ready_check: ReadyCheck | None = None,
    cache_max_age: int | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="catalog", lifespan=lifespan)
    for name, value in {
        "reader_factory": reader_factory,
        "ready_check": ready_check,
        "cache_max_age": cache_max_age,
    }.items():
        if value is not None:
            setattr(app.state, name, value)
    app.include_router(build_router())

    @app.exception_handler(ProductNotFound)
    async def not_found(_: Request, exc: ProductNotFound) -> JSONResponse:
        return JSONResponse({"detail": "product not found"}, status_code=404)

    @app.exception_handler(InvalidQuery)
    async def invalid_query(_: Request, exc: InvalidQuery) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"] if part != "query")
        return JSONResponse({"detail": f"invalid {location}: {first['msg']}"}, status_code=422)

    return app
