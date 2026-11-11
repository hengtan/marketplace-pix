from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Any, Protocol
from uuid import UUID

import httpx
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from payments.application.confirm_payment import ConfirmPayment, ConfirmResult
from payments.application.errors import PaymentNotFound, PspUnavailable
from payments.application.get_payment import GetPaymentByOrder
from payments.application.ports import PspGateway, UnitOfWork
from payments.domain.errors import DomainError
from payments.interface.metrics import PAYMENTS_CONFIRMED
from payments.interface.schemas import PaymentOut
from payments.interface.webhook_security import sign, verify

UowFactory = Callable[[], UnitOfWork]
ReadyCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


class DevPspControl(Protocol):
    async def mark_paid(self, charge_id: str) -> bool: ...


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/webhooks/psp")
    async def psp_webhook(
        request: Request,
        x_signature: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        body = await request.body()
        secret: str = request.app.state.webhook_secret
        if not x_signature or not verify(secret, body, x_signature):
            raise HTTPException(401, "invalid signature")
        try:
            data: Any = json.loads(body)
        except ValueError:
            raise HTTPException(400, "body must be JSON") from None
        if not isinstance(data, dict) or data.get("event") != "charge.paid":
            return JSONResponse({"status": "ignored"})
        charge_id = data.get("charge_id")
        if not isinstance(charge_id, str) or not charge_id:
            raise HTTPException(400, "charge_id is required")

        use_case = ConfirmPayment(request.app.state.uow_factory, request.app.state.psp)
        result = await use_case.execute(charge_id)
        if result is ConfirmResult.NOT_PAID:
            raise HTTPException(409, "PSP does not confirm this charge as paid")
        if result is ConfirmResult.CONFIRMED:
            PAYMENTS_CONFIRMED.inc()
        return JSONResponse({"status": result.value.lower()})

    @router.get("/payments/by-order/{order_id}", response_model=PaymentOut)
    async def get_payment(order_id: UUID, request: Request) -> PaymentOut:
        payment = await GetPaymentByOrder(request.app.state.uow_factory).execute(order_id)
        return PaymentOut.from_domain(payment)

    @router.post("/dev/psp/charges/{charge_id}/pay")
    async def dev_pay(charge_id: str, request: Request) -> JSONResponse:
        dev: DevPspControl | None = getattr(request.app.state, "dev_psp", None)
        if dev is None:
            raise HTTPException(404, "not found")
        if not await dev.mark_paid(charge_id):
            raise HTTPException(409, "charge cannot be paid (unknown, already paid or expired)")
        body = json.dumps({"event": "charge.paid", "charge_id": charge_id}).encode()
        transport = httpx.ASGITransport(app=request.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://internal") as client:
            response = await client.post(
                "/webhooks/psp",
                content=body,
                headers={"X-Signature": sign(request.app.state.webhook_secret, body)},
            )
        return JSONResponse(
            {"webhook_status": response.status_code, "webhook_body": response.json()}
        )

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
    psp: PspGateway | None = None,
    webhook_secret: str | None = None,
    dev_psp: DevPspControl | None = None,
    ready_check: ReadyCheck | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="payments", lifespan=lifespan)
    for name, value in {
        "uow_factory": uow_factory,
        "psp": psp,
        "webhook_secret": webhook_secret,
        "dev_psp": dev_psp,
        "ready_check": ready_check,
    }.items():
        if value is not None:
            setattr(app.state, name, value)
    app.include_router(build_router())

    @app.exception_handler(PaymentNotFound)
    async def not_found(_: Request, exc: PaymentNotFound) -> JSONResponse:
        return JSONResponse({"detail": "payment not found"}, status_code=404)

    @app.exception_handler(PspUnavailable)
    async def psp_unavailable(_: Request, exc: PspUnavailable) -> JSONResponse:
        retry_after = str(max(1, math.ceil(exc.retry_after_seconds)))
        return JSONResponse(
            {"detail": "payment provider temporarily unavailable", "code": "psp_unavailable"},
            status_code=503,
            headers={"Retry-After": retry_after},
        )

    @app.exception_handler(DomainError)
    async def domain_conflict(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    return app
