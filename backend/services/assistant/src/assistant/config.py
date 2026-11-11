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
    retrieval_rewrite: Literal["off", "always", "adaptive"] = "always"
    retrieval_typo_correction: bool = True
    retrieval_hyde: bool = False
    retrieval_decompose: bool = True
    retrieval_negation: bool = True
    retrieval_parent_documents: bool = True

    kafka_bootstrap_servers: str = "localhost:9094"
    cache_enabled: bool = True
    cache_threshold: float = 0.92
    cache_ttl_seconds: int = 3600
    llm_price_prompt_per_1k: float = 0.0005
    llm_price_completion_per_1k: float = 0.0015

    budget_enabled: bool = True
    budget_session_tokens: int = 20_000
    budget_session_cost_usd: float = 0.05
    budget_user_daily_tokens: int = 100_000
    budget_user_daily_cost_usd: float = 0.25

    llm_first_token_timeout_seconds: float = 15.0
    llm_token_idle_timeout_seconds: float = 10.0
    llm_total_timeout_seconds: float = 60.0
    tool_timeout_seconds: float = 8.0
    planner: Literal["rules", "llm"] = "rules"
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
