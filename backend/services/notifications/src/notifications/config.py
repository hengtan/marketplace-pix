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
    notifications_db: str = "notifications"
    kafka_bootstrap_servers: str = "localhost:9094"
    celery_broker_url: str = "redis://localhost:6380/1"
    celery_result_backend: str = "redis://localhost:6380/1"
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    mail_from: str = "Marketplace PIX <no-reply@marketplace-pix.local>"
    admin_email: str = "admin@marketplace-pix.local"
    frontend_base_url: str = "http://localhost:5173"
    timezone: str = "America/Sao_Paulo"
    requeue_after_seconds: int = 60
    requeue_interval_seconds: int = 30
    retry_base_seconds: float = 2.0
    daily_summary_hour: int = 23
    daily_summary_minute: int = 55

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.notifications_db}"
        )


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
