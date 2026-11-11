from pathlib import Path
from typing import Annotated

from marketplace_common.resilience import RedisFailureMode
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    identity_url: str = "http://localhost:8008"

    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    upstream_timeout: float = 10.0
    enable_dev_routes: bool = False
    rate_limit_per_minute: int = 600
    rate_limit_routes: dict[str, int] = {"ordering": 120, "assistant": 60}
    rate_limit_failure_mode: RedisFailureMode = RedisFailureMode.FALLBACK
    rate_limit_redis_timeout: float = 0.25
    redis_url: str = ""

    max_request_body_bytes: int = 1_048_576
    hsts_enabled: bool = False
    hsts_max_age_seconds: int = 31_536_000
    cross_origin_resource_policy: str = "same-site"
    trusted_proxies: Annotated[list[str], NoDecode] = []

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
    auth_enabled: bool = True
    revocation_cache_seconds: float = 0.5
    revocation_fail_open: bool = True
    allow_guest_checkout: bool = True
    internal_auth_secret: str = ""
    jwt_issuer: str = "marketplace-identity"
    jwt_audience: str = "marketplace-api"

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def _split_proxies(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    def upstreams(self) -> dict[str, str]:
        return {
            "catalog": self.catalog_url,
            "inventory": self.inventory_url,
            "ordering": self.ordering_url,
            "payments": self.payments_url,
            "ledger": self.ledger_url,
            "notifications": self.notifications_url,
            "assistant": self.assistant_url,
            "identity": self.identity_url,
        }
