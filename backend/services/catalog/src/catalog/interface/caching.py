from __future__ import annotations

import hashlib

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

DEFAULT_MAX_AGE = 0


def compute_etag(body: bytes) -> str:
    return f'"{hashlib.sha256(body).hexdigest()[:32]}"'


def _normalize(tag: str) -> str:
    tag = tag.strip()
    return tag.removeprefix("W/")


def matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    if if_none_match.strip() == "*":
        return True
    return any(_normalize(candidate) == etag for candidate in if_none_match.split(","))


def cached_json(request: Request, payload: BaseModel | list[BaseModel]) -> Response:
    max_age: int = getattr(request.app.state, "cache_max_age", DEFAULT_MAX_AGE)
    directive = (
        "public, max-age=0, must-revalidate" if max_age <= 0 else f"public, max-age={max_age}"
    )
    headers = {"Cache-Control": directive}
    response = JSONResponse(jsonable_encoder(payload), headers=headers)
    etag = compute_etag(bytes(response.body))
    headers["ETag"] = etag
    if matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    response.headers["ETag"] = etag
    return response
