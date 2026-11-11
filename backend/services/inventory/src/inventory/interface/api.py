from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from inventory.application.ports import UnitOfWork
from inventory.application.stock_queries import GetStock, SetStock
from inventory.domain.errors import DomainError
from inventory.interface.schemas import SetStockIn, StockOut

UowFactory = Callable[[], UnitOfWork]
ReadyCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]

MAX_PRODUCT_IDS = 200


def _parse_ids(raw: str) -> list[UUID]:
    try:
        ids = [UUID(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise HTTPException(422, "product_ids must be comma separated uuids") from None
    if len(ids) > MAX_PRODUCT_IDS:
        raise HTTPException(422, f"at most {MAX_PRODUCT_IDS} product_ids per request")
    return ids


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/stock", response_model=list[StockOut])
    async def list_stock(request: Request, product_ids: str | None = None) -> list[StockOut]:
        query = GetStock(request.app.state.uow_factory)
        if product_ids is None:
            stocks = await query.list_all()
        else:
            stocks = await query.execute(_parse_ids(product_ids))
        return [StockOut.from_domain(s) for s in stocks]

    @router.get("/stock/{product_id}", response_model=StockOut)
    async def get_stock(product_id: UUID, request: Request) -> StockOut:
        (stock,) = await GetStock(request.app.state.uow_factory).execute([product_id])
        return StockOut.from_domain(stock)

    @router.put("/stock/{product_id}", response_model=StockOut)
    async def put_stock(product_id: UUID, body: SetStockIn, request: Request) -> StockOut:
        stock = await SetStock(request.app.state.uow_factory).execute(product_id, body.available)
        return StockOut.from_domain(stock)

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
    uow_factory: UowFactory | None = None,
    ready_check: ReadyCheck | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="inventory", lifespan=lifespan)
    for name, value in {"uow_factory": uow_factory, "ready_check": ready_check}.items():
        if value is not None:
            setattr(app.state, name, value)
    app.include_router(build_router())

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    return app
