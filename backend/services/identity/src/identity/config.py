from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _find_env_file() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


ROOT_ENV = _find_env_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    postgres_user: str
    postgres_password: str
    postgres_host: str = "localhost"
    postgres_port: int = 5433
    identity_db: str = "identity"

    environment: str = "development"
    internal_auth_secret: str = ""
    identity_signing_key: str = ""
    identity_retired_public_keys: list[str] = []
    identity_seed_password: str = ""
    redis_url: str = ""
    redis_timeout_seconds: float = 0.5
    trusted_proxies: Annotated[list[str], NoDecode] = []
    abuse_protection_enabled: bool = True
    auth_login_per_minute_ip_email: int = 10
    auth_login_per_minute_ip: int = 60
    auth_register_per_hour_ip_email: int = 5
    auth_register_per_hour_ip: int = 30
    auth_backoff_base_seconds: float = 2.0
    auth_backoff_max_seconds: float = 900.0

    issuer: str = "marketplace-identity"
    audience: str = "marketplace-api"
    access_ttl_seconds: int = 600
    refresh_ttl_days: int = 14
    session_max_days: int = 30
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 4

    refresh_retention_days: int = 7
    cleanup_interval_seconds: float = 300.0
    cleanup_batch_size: int = 1000

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def _split_proxies(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.identity_db}"
        )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
