from __future__ import annotations


class ResilienceError(Exception):
    """Base das falhas geradas pelos padrões de resiliência (não pela dependência)."""

    retry_after_seconds: float = 1.0


class CircuitOpenError(ResilienceError):
    def __init__(self, name: str, retry_after_seconds: float) -> None:
        super().__init__(f"circuit '{name}' is open")
        self.name = name
        self.retry_after_seconds = retry_after_seconds


class BulkheadFullError(ResilienceError):
    def __init__(self, name: str, reason: str, retry_after_seconds: float = 1.0) -> None:
        super().__init__(f"bulkhead '{name}' rejected the call ({reason})")
        self.name = name
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


class DeadlineExceeded(ResilienceError):
    def __init__(self, message: str = "request deadline exceeded") -> None:
        super().__init__(message)
        self.retry_after_seconds = 0.0
