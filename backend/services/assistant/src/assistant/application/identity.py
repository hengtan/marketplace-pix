from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from marketplace_common.security import Principal


@dataclass(frozen=True, slots=True)
class CallerIdentity:
    principal: Principal | None
    request_id: str


_current: ContextVar[CallerIdentity | None] = ContextVar("assistant_caller_identity", default=None)


def current_identity() -> CallerIdentity | None:
    return _current.get()


def set_identity(identity: CallerIdentity | None) -> None:
    _current.set(identity)


@contextmanager
def bind_identity(identity: CallerIdentity | None) -> Iterator[None]:
    token = _current.set(identity)
    try:
        yield
    finally:
        _current.reset(token)
