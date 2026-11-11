import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from assistant.application.agent import AgentLoop
from assistant.application.chat import ChatService
from assistant.application.guardrails import GroundingGuard
from assistant.application.ingest import IngestCatalog
from assistant.application.planner import RuleBasedPlanner
from assistant.application.ports import (
    CatalogGateway,
    ChunkStore,
    Embedder,
    EvalStore,
    InventoryGateway,
    LlmClient,
    OrderGateway,
    Tool,
)
from assistant.application.prompt import PromptBuilder
from assistant.application.rerank import LexicalReranker
from assistant.application.retrieval import HybridRetriever, RetrievalConfig
from assistant.application.semantic_cache import CacheConfig, SemanticCache
from assistant.application.tools import (
    GetOrderStatusTool,
    GetPolicyTool,
    GetStockTool,
    SearchProductsTool,
)
from assistant.application.understanding import QueryUnderstanding
from assistant.config import Settings
from assistant.domain.chunking import RecursiveChunker
from assistant.domain.cost import CostModel
from assistant.infrastructure.db.cache_store import PgCacheStore
from assistant.infrastructure.db.chunk_store import PgChunkStore
from assistant.infrastructure.db.eval_store import PgEvalStore
from assistant.infrastructure.db.session import build_session_factory
from assistant.infrastructure.db.session_store import PgSessionStore
from assistant.infrastructure.embedders.hashing import HashingEmbedder
from assistant.infrastructure.embedders.ollama import OllamaEmbedder
from assistant.infrastructure.http.gateways import (
    HttpCatalogGateway,
    HttpInventoryGateway,
    HttpOrderGateway,
)
from assistant.infrastructure.llm.mock import MockLlm
from assistant.infrastructure.llm.ollama import OllamaLlm

NAMES_TTL_SECONDS = 60.0


@dataclass
class Container:
    settings: Settings
    chat: ChatService
    ingest: IngestCatalog
    retriever: HybridRetriever
    eval_store: EvalStore
    embedder: Embedder
    llm: LlmClient
    cache: SemanticCache
    clients: list[httpx.AsyncClient] = field(default_factory=list)

    async def aclose(self) -> None:
        for client in self.clients:
            await client.aclose()


def build_embedder(settings: Settings, client: httpx.AsyncClient) -> Embedder:
    if settings.embedder == "ollama":
        return OllamaEmbedder(
            client, settings.ollama_embed_model, settings.embedding_dim, settings.ollama_url
        )
    return HashingEmbedder(settings.embedding_dim)


def build_llm(settings: Settings, client: httpx.AsyncClient) -> LlmClient:
    if settings.llm == "ollama":
        return OllamaLlm(client, settings.ollama_chat_model, settings.ollama_url)
    return MockLlm()


NamesProvider = Callable[[], Awaitable[Sequence[str]]]


def _names_provider(store: ChunkStore, embedder: Embedder) -> NamesProvider:
    cache: dict[str, tuple[float, Sequence[str]]] = {}

    async def provide() -> Sequence[str]:
        hit = cache.get("names")
        if hit and time.monotonic() - hit[0] < NAMES_TTL_SECONDS:
            return hit[1]
        names = await store.product_names(embedder.name)
        cache["names"] = (time.monotonic(), names)
        return names

    return provide


def retrieval_config(settings: Settings) -> RetrievalConfig:
    return RetrievalConfig(
        branch_limit=settings.retrieval_branch_limit,
        candidates=settings.retrieval_candidates,
        final=settings.retrieval_final,
        rrf_k=settings.rrf_k,
        min_score=settings.retrieval_min_score,
        relative_cutoff=settings.retrieval_relative_cutoff,
        rewrite=settings.retrieval_rewrite,
        typo_correction=settings.retrieval_typo_correction,
        hyde=settings.retrieval_hyde,
        decompose=settings.retrieval_decompose,
        negation=settings.retrieval_negation,
        parent_documents=settings.retrieval_parent_documents,
    )


def build_container(
    settings: Settings,
    engine: AsyncEngine,
    *,
    catalog: CatalogGateway | None = None,
    inventory: InventoryGateway | None = None,
    orders: OrderGateway | None = None,
    embedder: Embedder | None = None,
    llm: LlmClient | None = None,
    http_client: httpx.AsyncClient | None = None,
    token_delay_seconds: float | None = None,
) -> Container:
    owned: list[httpx.AsyncClient] = []
    client = http_client
    if client is None:
        client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
        owned.append(client)
    ollama_client = httpx.AsyncClient(timeout=settings.ollama_timeout_seconds)
    owned.append(ollama_client)
    catalog = catalog or HttpCatalogGateway(client, settings.catalog_url)
    inventory = inventory or HttpInventoryGateway(client, settings.inventory_url)
    orders = orders or HttpOrderGateway(client, settings.ordering_url)
    embedder = embedder or build_embedder(settings, ollama_client)
    llm = llm or build_llm(settings, ollama_client)

    factory = build_session_factory(engine)
    store = PgChunkStore(factory)
    understanding = QueryUnderstanding(store, embedder.name)
    retriever = HybridRetriever(
        store,
        embedder,
        LexicalReranker(),
        retrieval_config(settings),
        understanding,
    )
    tools: dict[str, Tool] = {
        "search_products": SearchProductsTool(retriever),
        "get_stock": GetStockTool(inventory, catalog),
        "get_order_status": GetOrderStatusTool(orders),
        "get_policy": GetPolicyTool(),
    }
    agent = AgentLoop(RuleBasedPlanner(), tools, settings.agent_max_steps, understanding)
    delay = token_delay_seconds
    if delay is None:
        delay = settings.stream_token_delay_ms / 1000
    cost = CostModel(settings.llm_price_prompt_per_1k, settings.llm_price_completion_per_1k)
    cache = SemanticCache(
        PgCacheStore(factory),
        embedder,
        understanding,
        CacheConfig(settings.cache_enabled, settings.cache_threshold, settings.cache_ttl_seconds),
        cost,
    )
    chat = ChatService(
        agent,
        PromptBuilder(),
        llm,
        PgSessionStore(factory),
        GroundingGuard(),
        _names_provider(store, embedder),
        max_message_chars=settings.max_message_chars,
        history_window=settings.history_window,
        token_delay_seconds=delay,
        cache=cache,
        cost=cost,
    )
    ingest = IngestCatalog(
        catalog,
        store,
        embedder,
        RecursiveChunker(settings.chunk_size, settings.chunk_overlap),
    )
    return Container(
        settings, chat, ingest, retriever, PgEvalStore(factory), embedder, llm, cache, owned
    )
