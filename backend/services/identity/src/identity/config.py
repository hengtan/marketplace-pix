from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
