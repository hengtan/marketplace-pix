from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

BREAKER_STATE = Gauge(
    "resilience_circuit_breaker_state",
    "Circuit breaker state (1 for the current state, 0 for the others)",
    ["name", "state"],
)
BREAKER_TRANSITIONS = Counter(
    "resilience_circuit_breaker_transitions_total",
    "Circuit breaker state transitions",
    ["name", "from_state", "to_state"],
)
BREAKER_CALLS = Counter(
    "resilience_circuit_breaker_calls_total",
    "Calls seen by the circuit breaker by outcome (success, failure, slow, ignored)",
    ["name", "outcome"],
)
BREAKER_REJECTED = Counter(
    "resilience_circuit_breaker_rejected_total",
    "Calls rejected without reaching the dependency because the circuit was open",
    ["name"],
)

RETRY_EVENTS = Counter(
    "resilience_retry_events_total",
    "Retry outcomes (retried, exhausted, budget_denied, deadline, not_retryable)",
    ["name", "event"],
)

BULKHEAD_IN_FLIGHT = Gauge("resilience_bulkhead_in_flight", "Calls running", ["name"])
BULKHEAD_QUEUED = Gauge("resilience_bulkhead_queued", "Calls waiting for a slot", ["name"])
BULKHEAD_REJECTED = Counter(
    "resilience_bulkhead_rejected_total", "Calls rejected by the bulkhead", ["name", "reason"]
)
BULKHEAD_WAIT = Histogram(
    "resilience_bulkhead_wait_seconds",
    "Time spent waiting for a bulkhead slot",
    ["name"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)

RATE_LIMIT_DECISIONS = Counter(
    "resilience_rate_limit_decisions_total",
    "Rate limit decisions by route and result (allowed, limited)",
    ["route", "result"],
)
RATE_LIMIT_BACKEND = Counter(
    "resilience_rate_limit_backend_total",
    "Which limiter answered (redis, memory_fallback, fail_open, fail_closed)",
    ["backend"],
)

DEADLINE_EXCEEDED = Counter(
    "resilience_deadline_exceeded_total", "Requests that ran out of time budget", ["where"]
)
