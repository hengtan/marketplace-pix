from __future__ import annotations

from dataclasses import dataclass

MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = MAX_ATTEMPTS
    base_seconds: float = 2.0
    cap_seconds: float = 300.0

    def delay_after(self, attempt: int) -> float:
        return min(self.base_seconds * float(2 ** (attempt - 1)), self.cap_seconds)

    def exhausted(self, attempts: int) -> bool:
        return attempts >= self.max_attempts
