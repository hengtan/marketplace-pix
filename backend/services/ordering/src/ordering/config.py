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
    ordering_db: str = "ordering"
    kafka_bootstrap_servers: str = "localhost:9094"
    catalog_url: str = "http://localhost:8003"
    internal_auth_secret: str = ""
    saga_timeout_seconds: float = 2700.0
    saga_sweep_interval_seconds: float = 30.0
    saga_sweep_batch_size: int = 100

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.ordering_db}"
        )


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
