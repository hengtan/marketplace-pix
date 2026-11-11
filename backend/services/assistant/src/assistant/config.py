from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
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
    postgres_port: int = Field(
        default=5434, validation_alias=AliasChoices("ASSISTANT_DB_PORT", "PGVECTOR_PORT")
    )
    assistant_db: str = "assistant"

    catalog_url: str = "http://localhost:8003"
    inventory_url: str = "http://localhost:8004"
    ordering_url: str = "http://localhost:8001"
    http_timeout_seconds: float = 3.0

    embedder: Literal["hashing", "ollama"] = "hashing"
    llm: Literal["mock", "ollama"] = "mock"
    embedding_dim: int = 256
    ollama_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_chat_model: str = "llama3.2"
    ollama_timeout_seconds: float = 60.0

    chunk_size: int = 300
    chunk_overlap: int = 60
    retrieval_branch_limit: int = 20
    retrieval_candidates: int = 10
    retrieval_final: int = 4
    rrf_k: int = 60
    retrieval_min_score: float = 0.1
    retrieval_relative_cutoff: float = 0.5

    agent_max_steps: int = 3
    max_message_chars: int = 1000
    history_window: int = 6
    stream_token_delay_ms: int = 25

    evals_cases_path: str = "evals/cases.yaml"
    eval_min_hit_at_3: float = 0.8
    eval_min_mrr: float = 0.6
    eval_min_groundedness: float = 1.0
    eval_min_tool_accuracy: float = 0.9
    eval_min_answer_pass: float = 0.85

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.assistant_db}"
        )


def load_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
