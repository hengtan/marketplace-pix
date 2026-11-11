from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.application.errors import IdempotencyKeyReused, OrderNotFound
from ordering.application.get_order import GetOrder
from ordering.application.ports import UnitOfWork
from ordering.domain.errors import DomainError
from ordering.interface.schemas import CreateOrderIn, CreateOrderOut, OrderOut

UowFactory = Callable[[], UnitOfWork]
ReadyCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]

MAX_KEY_LENGTH = 255


def get_uow_factory(request: Request) -> UowFactory:
    factory: UowFactory = request.app.state.uow_factory
    return factory


UowDep = Annotated[UowFactory, Depends(get_uow_factory)]


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/orders", status_code=201, response_model=CreateOrderOut)
    async def create_order(
        body: CreateOrderIn,
        response: Response,
        uow_factory: UowDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> CreateOrderOut:
        if not idempotency_key or len(idempotency_key) > MAX_KEY_LENGTH:
            raise HTTPException(400, "Idempotency-Key header is required (max 255 chars)")
        command = CreateOrderCommand(
            customer_id=body.customer_id,
            currency=body.currency,
            items=[
                CreateOrderItem(i.product_id, i.quantity, i.unit_price_cents) for i in body.items
            ],
        )
        result = await CreateOrder(uow_factory).execute(command, idempotency_key)
        if result.replayed:
            response.headers["Idempotent-Replayed"] = "true"
        return CreateOrderOut(id=result.order_id)

    @router.get("/orders/{order_id}", response_model=OrderOut)
    async def get_order(order_id: UUID, uow_factory: UowDep) -> OrderOut:
        return OrderOut.from_domain(await GetOrder(uow_factory).execute(order_id))

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
    app = FastAPI(title="ordering", lifespan=lifespan)
    if uow_factory is not None:
        app.state.uow_factory = uow_factory
    if ready_check is not None:
        app.state.ready_check = ready_check
    app.include_router(build_router())

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(IdempotencyKeyReused)
    async def key_reused(_: Request, exc: IdempotencyKeyReused) -> JSONResponse:
        return JSONResponse(
            {"detail": "Idempotency-Key was already used with a different request body"},
            status_code=422,
        )

    @app.exception_handler(OrderNotFound)
    async def not_found(_: Request, exc: OrderNotFound) -> JSONResponse:
        return JSONResponse({"detail": "order not found"}, status_code=404)

    return app
