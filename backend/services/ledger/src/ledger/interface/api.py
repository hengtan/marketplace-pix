from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from ledger.application.clock import Clock, utcnow
from ledger.application.errors import InvalidQuery
from ledger.application.ports import UnitOfWork
from ledger.application.queries import (
    MAX_DAYS,
    GetMerchantSummary,
    ListAccountEntries,
    Reconcile,
)
from ledger.interface.schemas import (
    EntriesPageOut,
    MerchantSummaryOut,
    ReconciliationOut,
)

UowFactory = Callable[[], UnitOfWork]
ReadyCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/merchants/{merchant_id}/summary", response_model=MerchantSummaryOut)
    async def merchant_summary(
        merchant_id: UUID,
        request: Request,
        days: Annotated[int, Query(ge=1, le=MAX_DAYS)] = 30,
    ) -> MerchantSummaryOut:
        use_case = GetMerchantSummary(request.app.state.uow_factory, request.app.state.clock)
        return MerchantSummaryOut.from_domain(await use_case.execute(merchant_id, days))

    @router.get("/accounts/{account_id}/entries", response_model=EntriesPageOut)
    async def account_entries(
        account_id: str,
        request: Request,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> EntriesPageOut:
        use_case = ListAccountEntries(request.app.state.uow_factory)
        return EntriesPageOut.from_domain(await use_case.execute(account_id, page, page_size))

    @router.get("/reconciliation", response_model=ReconciliationOut)
    async def reconciliation(request: Request) -> ReconciliationOut:
        use_case = Reconcile(request.app.state.uow_factory, request.app.state.clock)
        return ReconciliationOut.from_domain(await use_case.execute())

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
    clock: Clock = utcnow,
    ready_check: ReadyCheck | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="ledger", lifespan=lifespan)
    app.state.clock = clock
    if uow_factory is not None:
        app.state.uow_factory = uow_factory
    if ready_check is not None:
        app.state.ready_check = ready_check
    app.include_router(build_router())

    @app.exception_handler(InvalidQuery)
    async def invalid_query(_: Request, exc: InvalidQuery) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    return app
