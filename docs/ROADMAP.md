**English** | [Português (Brasil)](pt-BR/ROADMAP.md)

# Roadmap

Working rule: in every phase, write the tests before the hard part and try to break things on purpose (the same request twice, killing a worker midway, a duplicate message, a dependency that goes down).

## Delivered

### Core domain and saga
- [x] `ordering`: `Order` aggregate, `Money` value object, Unit of Work, `Idempotency-Key` claimed in the same transaction as the order (tested with 5 concurrent requests), outbox with trace context, relay to Kafka keyed by order id
- [x] `payments`: PIX charge behind a PSP port (idempotent by reference), HMAC webhook that also queries the PSP before confirming (fail-closed), inbox, expiration job, charge cancelled at the PSP on expiry
- [x] Choreographed saga across `ordering`, `payments`, `inventory`, `ledger` and `notifications`; order row locked with `FOR UPDATE` so concurrent confirm and expire have one winner
- [x] Global saga timeout (`SagaTimeoutManager`), and a late payment is refunded idempotently and audited (`PaymentRefundRequested`, `PaymentRefunded`, ledger reversal, stock returned)
- [x] `ledger`: double entry that rejects unbalanced transactions, 10% platform split with rounding that always balances, 50 concurrent payments keep the balance exact, reconciliation endpoint
- [x] `inventory`: all-or-nothing reservation with TTL (100 reservations for 10 units accept exactly 10), release and refund restock, stock row created automatically when a product is created, deactivated products leave the merchant list
- [x] `notifications`: emails through Celery and Mailpit, retry, sweeper, daily digest
- [x] `catalog`: accent-insensitive search, filters, sorting, ETag and revalidation, merchant write API (create, edit, deactivate, reactivate, owner list), `catalog.events` through an outbox, seed that never overwrites merchant edits

### Resilience
- [x] Bounded retries and a dead-letter queue (`<topic>.dlq`) in every consumer, plus a reprocessing tool (`marketplace_common.dlq`, dry run by default)
- [x] Circuit breaker (sliding window, failure and slow-call rates, half-open probes), retry with full jitter and a retry budget, deadline propagation, bulkhead
- [x] Distributed rate limit on Redis (token bucket in Lua) with configurable failure mode, trusted `X-Forwarded-For`
- [x] Applied to the gateway, the PSP client, the webhook, and the assistant's LLM and embedder
- [x] Optional breaker state shared across replicas (`BREAKER_SHARED_STATE`)
- [x] `scripts/chaos.sh`, `scripts/loadtest.py`, SLO dashboard and burn-rate alerts

### Security and platform
- [x] `identity` service: argon2id, EdDSA JWT with JWKS, rotating refresh tokens with reuse detection, roles and scopes
- [x] Gateway validates the token, strips client identity headers and signs the identity for services
- [x] Object-level authorization and multi-tenancy (merchant ledger, stock, orders), with BOLA and isolation tests
- [x] Access token revocation, sign-up and login throttling with progressive backoff, security headers, body size limit
- [x] Event versioning (`schema_version`, upcasters, golden files, contract tests), batched retention of outbox, inbox, idempotency keys and refresh tokens

### AI
- [x] `assistant` service: chunking, pgvector HNSW, hybrid search with RRF, reranker, filters, agent loop with tools, memory, guardrails
- [x] Query understanding, semantic cache with event-driven invalidation, MMR, parent-document retrieval
- [x] Evaluation with 111 cases and a CI regression gate; 41 red-team attacks contained; per-stage OpenTelemetry spans, token and cost metrics, streaming with cancellation and graceful fallback
- [x] Models are simulated behind interfaces (embeddings by feature hashing, deterministic LLM); Ollama adapters are ready and tested against a fake HTTP server

### Frontend
- [x] "Praça" storefront (React 19, Tailwind v4, Radix, Motion, ⌘K): live PIX flow, assistant chat with citations and trace, login and signup
- [x] Merchant panel with five URL-addressed tabs (overview, orders, stock, products, statement), inline stock editing with rollback, reactivation of deactivated products, keyboard shortcuts, CSV export
- [x] Lighthouse desktop 99, axe clean on every route in light and dark, route transitions that respect `prefers-reduced-motion`

### Quality and delivery
- [x] OpenTelemetry traces that cross Kafka, Prometheus RED metrics, Grafana dashboards (marketplace, resilience, assistant)
- [x] GitHub Actions with per-service lint, format, strict typing, unit and integration jobs, the RAG regression gate, and the frontend job
- [x] End-to-end scripts: `scripts/e2e.sh` (114 checks), `scripts/e2e-saga.sh` (27), `scripts/chaos.sh` (40)

## Not built yet

- [ ] Azure with Terraform (Container Apps or AKS, Key Vault, budget alert) and Kubernetes with Helm (k3d locally): postponed on purpose
- [ ] Real models through Ollama (or a managed provider) and a re-evaluation against the same 111 cases
- [ ] MFA, email verification, and an `HttpOnly` refresh cookie through a BFF (see the limitations in `docs/SECURITY.md`)
- [ ] An explicit saga orchestrator (the saga is choreographed, with a process manager only for the deadline)
- [ ] A Prometheus scrape job for `assistant-worker`
- [ ] SSR or prerendering of the storefront home to move mobile Lighthouse from 88 to 91 to a stable 90 or more
- [ ] A test that runs every service's Alembic migrations from scratch
