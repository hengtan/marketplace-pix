from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Any
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from marketplace_common.security import Principal, PrincipalResolver, Scope

from identity.application.auth import AuthService
from identity.application.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
    UserNotFound,
)
from identity.domain.errors import DomainError
from identity.interface.schemas import (
    AdminCreateUserIn,
    LoginIn,
    RefreshIn,
    RegisterIn,
    TokensOut,
    UserOut,
)

ReadyCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def merchant_id_for_slug(slug: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"marketplace-pix:merchant:{slug}")


def get_auth(request: Request) -> AuthService:
    auth: AuthService = request.app.state.auth
    return auth


def get_principal(request: Request) -> Principal | None:
    resolver: PrincipalResolver = request.app.state.principal_resolver
    return resolver(request)


AuthDep = Annotated[AuthService, Depends(get_auth)]
PrincipalDep = Annotated[Principal | None, Depends(get_principal)]


def require(principal: Principal | None, scope: Scope | None = None) -> Principal:
    if principal is None:
        raise HTTPException(401, "authentication required")
    if scope is not None and not principal.can(scope):
        raise HTTPException(403, "forbidden")
    return principal


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/auth/register", status_code=201, response_model=TokensOut)
    async def register(body: RegisterIn, auth: AuthDep, response: Response) -> TokensOut:
        response.headers.update(NO_STORE)
        return TokensOut.from_domain(
            await auth.register_customer(body.email, body.name, body.password)
        )

    @router.post("/auth/login", response_model=TokensOut)
    async def login(body: LoginIn, auth: AuthDep, response: Response) -> TokensOut:
        response.headers.update(NO_STORE)
        return TokensOut.from_domain(await auth.login(body.email, body.password))

    @router.post("/auth/refresh", response_model=TokensOut)
    async def refresh(body: RefreshIn, auth: AuthDep, response: Response) -> TokensOut:
        response.headers.update(NO_STORE)
        return TokensOut.from_domain(await auth.refresh(body.refresh_token))

    @router.post("/auth/logout", status_code=204)
    async def logout(body: RefreshIn, auth: AuthDep) -> Response:
        await auth.logout(body.refresh_token)
        return Response(status_code=204, headers=NO_STORE)

    @router.get("/auth/me", response_model=UserOut)
    async def me(auth: AuthDep, principal: PrincipalDep) -> UserOut:
        current = require(principal)
        return UserOut.from_domain(await auth.get_user(current.user_id))

    @router.post("/auth/admin/users", status_code=201, response_model=UserOut)
    async def admin_create_user(
        body: AdminCreateUserIn, auth: AuthDep, principal: PrincipalDep
    ) -> UserOut:
        require(principal, Scope.USERS_MANAGE)
        merchant_id = body.merchant_id
        if merchant_id is None and body.merchant_slug:
            merchant_id = merchant_id_for_slug(body.merchant_slug)
        user = await auth.create_user(
            body.email, body.name, body.password, frozenset(body.roles), merchant_id
        )
        return UserOut.from_domain(user)

    @router.get("/.well-known/jwks.json")
    async def jwks(request: Request) -> JSONResponse:
        keys: dict[str, Any] = request.app.state.jwks
        return JSONResponse(keys, headers={"Cache-Control": "public, max-age=300"})

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
    auth: AuthService | None = None,
    jwks: dict[str, Any] | None = None,
    internal_secret: str = "",
    ready_check: ReadyCheck | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="identity", lifespan=lifespan)
    app.state.principal_resolver = PrincipalResolver(internal_secret)
    if auth is not None:
        app.state.auth = auth
    if jwks is not None:
        app.state.jwks = jwks
    if ready_check is not None:
        app.state.ready_check = ready_check
    app.include_router(build_router())

    @app.exception_handler(InvalidCredentials)
    async def invalid_credentials(_: Request, exc: InvalidCredentials) -> JSONResponse:
        return JSONResponse(
            {"detail": "invalid credentials"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer", **NO_STORE},
        )

    @app.exception_handler(InvalidRefreshToken)
    async def invalid_refresh(_: Request, exc: InvalidRefreshToken) -> JSONResponse:
        return JSONResponse(
            {"detail": "invalid refresh token"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer", **NO_STORE},
        )

    @app.exception_handler(EmailAlreadyRegistered)
    async def email_taken(_: Request, exc: EmailAlreadyRegistered) -> JSONResponse:
        return JSONResponse({"detail": "email already registered"}, status_code=409)

    @app.exception_handler(UserNotFound)
    async def user_missing(_: Request, exc: UserNotFound) -> JSONResponse:
        return JSONResponse({"detail": "user not found"}, status_code=404)

    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    return app
