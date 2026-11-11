from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse

from notifications.application.errors import NotificationNotFound
from notifications.application.ports import EmailRenderer, UnitOfWork
from notifications.application.queries import ListNotifications, PreviewNotification
from notifications.interface.schemas import NotificationOut, NotificationPage

UowFactory = Callable[[], UnitOfWork]
ReadyCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/notifications", response_model=NotificationPage)
    async def list_notifications(
        request: Request,
        customer_id: UUID | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> NotificationPage:
        items, total = await ListNotifications(request.app.state.uow_factory).execute(
            customer_id, page, page_size
        )
        return NotificationPage(
            items=[NotificationOut.from_domain(n) for n in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    @router.get("/notifications/{notification_id}/preview", response_class=HTMLResponse)
    async def preview(notification_id: UUID, request: Request) -> HTMLResponse:
        html = await PreviewNotification(
            request.app.state.uow_factory, request.app.state.renderer
        ).execute(notification_id)
        return HTMLResponse(html)

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
    renderer: EmailRenderer | None = None,
    ready_check: ReadyCheck | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="notifications", lifespan=lifespan)
    for name, value in {
        "uow_factory": uow_factory,
        "renderer": renderer,
        "ready_check": ready_check,
    }.items():
        if value is not None:
            setattr(app.state, name, value)
    app.include_router(build_router())

    @app.exception_handler(NotificationNotFound)
    async def not_found(_: Request, exc: NotificationNotFound) -> JSONResponse:
        return JSONResponse({"detail": "notification not found"}, status_code=404)

    return app
