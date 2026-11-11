from pathlib import Path

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
    identity_url: str = "http://localhost:8008"

    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    upstream_timeout: float = 10.0
    enable_dev_routes: bool = False
    rate_limit_per_minute: int = 600
    auth_enabled: bool = True
    allow_guest_checkout: bool = True
    internal_auth_secret: str = ""
    jwt_issuer: str = "marketplace-identity"
    jwt_audience: str = "marketplace-api"

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
