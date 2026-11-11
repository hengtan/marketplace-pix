from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from marketplace_common.security import Principal, PrincipalResolver, Scope

from ordering.application.access import can_view_order
from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.application.errors import (
    CatalogUnavailable,
    IdempotencyKeyReused,
    OrderNotFound,
    UnknownProduct,
)
from ordering.application.get_order import GetOrder
from ordering.application.list_orders import ListOrders
from ordering.application.ports import CatalogGateway, OwnerScope, UnitOfWork
from ordering.domain.errors import DomainError
from ordering.interface.metrics import ORDERS_CREATED
from ordering.interface.schemas import (
    CreateOrderIn,
    CreateOrderOut,
    MerchantOrderPageOut,
    OrderOut,
    OrderPageOut,
)

UowFactory = Callable[[], UnitOfWork]
ReadyCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]

MAX_KEY_LENGTH = 255


def get_uow_factory(request: Request) -> UowFactory:
    factory: UowFactory = request.app.state.uow_factory
    return factory


def get_catalog(request: Request) -> CatalogGateway:
    catalog: CatalogGateway = request.app.state.catalog
    return catalog


def get_principal(request: Request) -> Principal | None:
    resolver: PrincipalResolver = request.app.state.principal_resolver
    return resolver(request)


PrincipalDep = Annotated[Principal | None, Depends(get_principal)]
UowDep = Annotated[UowFactory, Depends(get_uow_factory)]
CatalogDep = Annotated[CatalogGateway, Depends(get_catalog)]


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/orders", status_code=201, response_model=CreateOrderOut)
    async def create_order(
        body: CreateOrderIn,
        response: Response,
        uow_factory: UowDep,
        catalog: CatalogDep,
        principal: PrincipalDep,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> CreateOrderOut:
        if not idempotency_key or len(idempotency_key) > MAX_KEY_LENGTH:
            raise HTTPException(400, "Idempotency-Key header is required (max 255 chars)")
        if principal is not None and not principal.can(Scope.ORDERS_CREATE):
            raise HTTPException(403, "forbidden")
        if principal is not None:
            if body.customer_id is not None and body.customer_id != principal.user_id:
                raise HTTPException(403, "customer_id does not match the authenticated user")
            customer_id = principal.user_id
        elif body.customer_id is not None:
            customer_id = body.customer_id
        else:
            raise HTTPException(422, "customer_id is required for guest checkout")
        command = CreateOrderCommand(
            owner_id=principal.user_id if principal is not None else None,
            customer_id=customer_id,
            customer_name=body.customer_name,
            customer_email=body.customer_email,
            items=[CreateOrderItem(i.product_id, i.quantity) for i in body.items],
        )
        result = await CreateOrder(uow_factory, catalog).execute(command, idempotency_key)
        if result.replayed:
            response.headers["Idempotent-Replayed"] = "true"
        else:
            ORDERS_CREATED.inc()
        return CreateOrderOut(id=result.order_id)

    @router.get("/orders/merchant", response_model=MerchantOrderPageOut)
    async def merchant_orders(
        uow_factory: UowDep,
        principal: PrincipalDep,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=50)] = 20,
        merchant_id: UUID | None = None,
    ) -> MerchantOrderPageOut:
        if principal is None:
            raise HTTPException(401, "authentication required")
        if not principal.can(Scope.ORDERS_READ_MERCHANT):
            raise HTTPException(403, "forbidden")
        if merchant_id is not None and not principal.can(Scope.ORDERS_READ_ANY):
            raise HTTPException(403, "forbidden")
        target = merchant_id or principal.merchant_id
        if target is None:
            raise HTTPException(403, "no merchant bound to this account")
        result = await ListOrders(uow_factory).for_merchant(target, page, page_size)
        return MerchantOrderPageOut.from_domain(result, target)

    @router.get("/orders", response_model=OrderPageOut)
    async def list_orders(
        uow_factory: UowDep,
        principal: PrincipalDep,
        customer_id: UUID | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> OrderPageOut:
        if principal is None:
            if customer_id is None:
                raise HTTPException(422, "customer_id is required")
            scope, target = OwnerScope.GUEST, customer_id
        elif principal.can(Scope.ORDERS_READ_ANY) and customer_id is not None:
            scope, target = OwnerScope.ANY, customer_id
        elif customer_id is not None and customer_id != principal.user_id:
            raise HTTPException(403, "forbidden")
        else:
            scope, target = OwnerScope.OWNED, principal.user_id
        return OrderPageOut.from_domain(
            await ListOrders(uow_factory).execute(target, page, page_size, scope)
        )

    @router.get("/orders/{order_id}", response_model=OrderOut)
    async def get_order(order_id: UUID, uow_factory: UowDep, principal: PrincipalDep) -> OrderOut:
        order = await GetOrder(uow_factory).execute(order_id)
        if not can_view_order(order, principal):
            raise OrderNotFound(str(order_id))
        return OrderOut.from_domain(order)

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
    catalog: CatalogGateway | None = None,
    internal_secret: str = "",
    ready_check: ReadyCheck | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="ordering", lifespan=lifespan)
    app.state.principal_resolver = PrincipalResolver(internal_secret)
    if uow_factory is not None:
        app.state.uow_factory = uow_factory
    if catalog is not None:
        app.state.catalog = catalog
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

    @app.exception_handler(UnknownProduct)
    async def unknown_product(_: Request, exc: UnknownProduct) -> JSONResponse:
        return JSONResponse({"detail": f"unknown product: {exc}"}, status_code=422)

    @app.exception_handler(CatalogUnavailable)
    async def catalog_unavailable(_: Request, exc: CatalogUnavailable) -> JSONResponse:
        return JSONResponse({"detail": "catalog is unavailable, try again"}, status_code=503)

    @app.exception_handler(OrderNotFound)
    async def not_found(_: Request, exc: OrderNotFound) -> JSONResponse:
        return JSONResponse({"detail": "order not found"}, status_code=404)

    return app
