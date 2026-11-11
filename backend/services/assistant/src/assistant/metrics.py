from prometheus_client import Counter, Gauge, Histogram

CACHE_REQUESTS = Counter(
    "assistant_cache_requests_total", "Semantic cache lookups by outcome", ["result"]
)
CACHE_TOKENS_SAVED = Counter(
    "assistant_cache_tokens_saved_total", "Estimated LLM tokens avoided by cache hits"
)
CACHE_COST_SAVED = Counter(
    "assistant_cache_cost_saved_usd_total", "Estimated LLM cost avoided by cache hits"
)
CACHE_INVALIDATIONS = Counter(
    "assistant_cache_invalidations_total", "Cache entries removed", ["reason"]
)
CACHE_ENTRIES = Gauge("assistant_cache_entries", "Entries currently in the semantic cache")
CATALOG_EVENTS = Counter(
    "assistant_catalog_events_total", "Catalog events handled", ["event_type", "result"]
)
STEP_DURATION = Histogram(
    "assistant_step_duration_seconds",
    "Latency of each pipeline step",
    ["step"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

BUDGET_REJECTIONS = Counter(
    "assistant_budget_rejections_total", "Requests refused by the budget", ["scope", "limit"]
)
GUARDRAIL_EVENTS = Counter("assistant_guardrail_events_total", "Guardrail interventions", ["kind"])

CHAT_REQUESTS = Counter(
    "assistant_chat_requests_total", "Chat requests by intent and outcome", ["intent", "outcome"]
)
LLM_REQUESTS = Counter("assistant_llm_requests_total", "Model calls", ["model", "result"])
LLM_TOKENS = Counter(
    "assistant_llm_tokens_total", "Estimated tokens sent to and received from the model",
    ["model", "direction"],
)  # fmt: skip
LLM_COST = Counter("assistant_llm_cost_usd_total", "Estimated model cost in USD", ["model"])
RETRIEVAL_RESULTS = Counter(
    "assistant_retrieval_total", "Retrievals by whether they found passages", ["result"]
)
FALLBACKS = Counter("assistant_fallback_total", "Degraded answers by reason", ["reason"])
STREAMS_CANCELLED = Counter(
    "assistant_stream_cancelled_total", "Streams closed before the answer was complete"
)
STREAMS_ACTIVE = Gauge("assistant_streams_active", "Streams currently open")
