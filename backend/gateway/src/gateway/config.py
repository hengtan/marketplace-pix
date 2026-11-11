from pathlib import Path

from marketplace_common.resilience import RedisFailureMode
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_find_env_file(), extra="ignore")

    catalog_url: str = "http://localhost:8003"
    inventory_url: str = "http://localhost:8004"
    ordering_url: str = "http://localhost:8001"
    payments_url: str = "http://localhost:8002"
    ledger_url: str = "http://localhost:8005"
    notifications_url: str = "http://localhost:8006"
    assistant_url: str = "http://localhost:8007"

    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    upstream_timeout: float = 10.0
    enable_dev_routes: bool = False
    rate_limit_per_minute: int = 600
    rate_limit_routes: dict[str, int] = {"ordering": 120, "assistant": 60}
    rate_limit_failure_mode: RedisFailureMode = RedisFailureMode.FALLBACK
    rate_limit_redis_timeout: float = 0.25
    redis_url: str = ""

    request_deadline_seconds: float = 8.0
    max_request_deadline_seconds: float = 30.0
    service_deadlines: dict[str, float] = {"assistant": 25.0}

    breaker_failure_rate: float = 0.5
    breaker_slow_call_seconds: float | None = None
    breaker_minimum_calls: int = 10
    breaker_window_size: int = 20
    breaker_window_seconds: float = 30.0
    breaker_open_seconds: float = 10.0
    breaker_half_open_calls: int = 3

    retry_attempts: int = 3
    retry_base_delay: float = 0.05
    retry_max_delay: float = 0.5
    retry_budget_ratio: float = 0.2

    bulkhead_max_concurrent: int = 100
    bulkhead_max_queue: int = 50
    bulkhead_queue_timeout: float = 1.0

    def upstreams(self) -> dict[str, str]:
        return {
            "catalog": self.catalog_url,
            "inventory": self.inventory_url,
            "ordering": self.ordering_url,
            "payments": self.payments_url,
            "ledger": self.ledger_url,
            "notifications": self.notifications_url,
            "assistant": self.assistant_url,
        }
