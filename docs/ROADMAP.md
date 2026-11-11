**English** | [Português (Brasil)](pt-BR/ROADMAP.md)

# Roadmap

Golden rule: in each phase, write the tests before the hard part and try to break things on purpose
(the same request twice, killing the worker midway, a duplicate message).

## Phase 0: Foundation (local infra)
- [x] Folder structure and README
- [x] `docker compose up` brings up Postgres, Redis, and Kafka (with topics created)
- [ ] Service pattern defined (a template reused by the others)

## Phase 1: `ordering` (TACKLE FIRST)
Reason: it is the heart of the system. The domain (DDD), ACID with Unit of Work, the outbox, and later the saga all live here.
- [x] `Order` aggregate, `Money` value object, domain events
- [x] Use case: create order (UoW + port)
- [x] Use case: get order
- [ ] Use case: cancel order
- [x] `Idempotency-Key` on POST (claim in the same transaction as the order; tested with 5 concurrent requests)
- [x] FastAPI API (`POST /orders`, `GET /orders/{id}`, `/health`, `/ready`) + Dockerfile + compose (`services` profile)
- [x] `outbox_events` table written in the same transaction as the order (Alembic migration)
- [x] Outbox relay publishing to Kafka (key = order_id)
- [x] Tests: domain unit tests, integration with real Postgres and Kafka
- [ ] Test that runs the Alembic migrations from scratch
- [ ] Price coming from the catalog (today the client sends `unit_price_cents`)
- [x] Cleanup (TTL) of `idempotency_keys` and published outbox rows (batched job in `marketplace_common.maintenance`)

## Phase 2: `payments` (DONE)
- [x] `Payment` domain (PENDING, CONFIRMED, EXPIRED), deterministic id per order, confirm/expire rules
- [x] Simulated PSP behind a port (`PspGateway`), idempotent by `reference`
- [x] Kafka consumer for `orders.events` with an **inbox** (dedupe by `event_id`, in the same transaction as the charge)
- [x] Webhook with HMAC (401 without a valid signature) that still **queries the PSP** before confirming (fail-closed, 409 if unpaid)
- [x] Expiration job (`ExpirePayments`) and `PaymentCreated`, `PaymentConfirmed`, `PaymentExpired` events via outbox/relay
- [x] 53 tests (unit + integration with real Postgres and Kafka), Dockerfile, and 4 services in compose
- [ ] Message that always fails (poison): limited retry and `orders.events.dlq`
- [x] Cleanup (TTL) of the inbox and the published outbox
- [x] Refund of a late payment (`PaymentRefundRequested`, `PaymentRefunded`, ledger reversal, and stock returned)
- [x] Cancel the charge at the PSP when it expires (if the PSP refuses because it was already paid, the payment stays pending for the webhook)
- [x] `payments/by-order` right after creating the order responds `202` with `Retry-After` instead of `404`
- [ ] Extract outbox, relay, and inbox to `backend/libs` (today copied from ordering)

## Phase 3: Complete saga (ordering + payments) (DONE)
- [x] `ordering` consumes `payments.events` with an inbox: `PaymentConfirmed` marks the order as paid, `PaymentExpired` cancels it
- [x] Order locked with `FOR UPDATE`: concurrent confirmation and expiration have a single winner (the other becomes a CONFLICT)
- [x] End-to-end test in the containers: paid order and order with an expired PIX
- [x] Conflict (payment confirmed for an already cancelled order) becomes an audit record in `order_audit` and a refund request
- [x] Global saga timeout (`SagaTimeoutManager` in ordering cancels an order stuck in PENDING with `saga timeout`)
- [ ] Explicit orchestrator (the saga is still choreographed by events, with the process manager only handling the deadline)
- [x] Automated end-to-end test across the services (`scripts/e2e.sh` and `scripts/e2e-saga.sh`)

## Phase 4: `ledger` (DONE)
- [x] Double entry (debits equal credits, an unbalanced transaction is rejected)
- [x] Merchant and platform split (10% per merchant, rounding that always balances)
- [x] Concurrency: 50 simultaneous payments keep the balance exact; property test (hypothesis)
- [x] Reconciliation (`/reconciliation`) and merchant summary with a daily series

## Phase 5: `inventory` and `notifications`
- [x] `inventory`: all-or-nothing reservation, no overselling (100 reservations for 10 units accept 10), TTL, release
- [x] Out of stock cancels the order and the charge (complete saga)
- [x] `notifications`: emails via Celery + Mailpit, retry, sweeper, daily digest

## Phase 6: `catalog`, gateway, and frontend
- [x] `catalog`: accent-insensitive search, filters, sorting, ETag/304, seed of 24 products
- [x] Order price and merchant come from the catalog (the client only sends product and quantity)
- [x] Gateway: contract routes, CORS, `Idempotency-Key`, `X-Request-Id`, request limit, aggregated health
- [x] "Praça" frontend (React 19, Tailwind v4, Radix, Motion, ⌘K, live PIX, merchant dashboard), served at http://localhost:5173 and verified in the browser against the real backend

## Resilience (DONE)
- [x] Limited retries and DLQ (`<topic>.dlq`) in all consumers
- [x] Tool to reprocess DLQ messages (`marketplace_common.dlq`, dry-run by default, loop protection)
- [x] Consumer, outbox, and relay extracted to `backend/libs/marketplace_common`

## Advanced resilience (DONE)
- [x] Circuit breaker (sliding window, failure and slowness, half-open probes), retry with full jitter and budget, deadline propagation, bulkhead
- [x] Distributed rate limit on Redis (token bucket in Lua) with configurable fallback and fail-open
- [x] Applied to the gateway, the PSP client, the webhook, and the assistant's LLM and embedder
- [x] `scripts/chaos.sh` (catalog, payments, and Redis), `scripts/loadtest.py`, SLO dashboard and alerts (burn rate)
- [x] Breaker state shared across replicas (optional, `BREAKER_SHARED_STATE`, only the decision to open is global)
- [x] Identify the client by a trusted `X-Forwarded-For` (`TRUSTED_PROXIES`) in the rate limit

## Phase 7: AI
- [ ] RAG over the catalog (pgvector)
- [ ] Agent with tool use (stock, order status)
- [ ] Evaluation (Promptfoo) and tracing (Langfuse)

## Phase 8: Platform
- [ ] OpenTelemetry, Prometheus, Grafana
- [ ] GitHub Actions (build, test, deploy)
- [ ] k3d + Helm (local) and Terraform + Azure Container Apps (cloud, with a budget alert)

## Phase 7: AI (DONE, with simulated models)
- [x] `assistant` service: ingestion with chunking and pgvector (HNSW), hybrid search with RRF, reranker, filters, agent with tools, memory, and guardrails
- [x] Evaluation with metrics (hit@k, MRR, context adherence) that fails the build below thresholds
- [x] Chat interface in the frontend (streaming, citations with photo and price, "How I got this answer" trace, memory)
- [x] Query understanding: intent (catalog, order, stock, policy, out of scope), rewriting with synonyms, typo correction, negation, and decomposition
- [x] Semantic cache (pgvector) with TTL and invalidation by catalog events (`catalog.events`), hit rate and savings metrics
- [x] Advanced retrieval: pre-search filters, fusion weights, MMR, parent-document; variants compared in `docs/RAG-EVALUATION.md`
- [x] Evaluation: 111 cases (dev and holdout), hit@k, MRR, nDCG, context precision and recall, `JudgeLlm` judge, CI regression gate
- [x] Guardrails: direct and indirect injection, PII in logs and traces, per-session and per-user budget, structured output with repair, numbers verified against the cited passage, 41 red-team attacks
- [x] LLM observability: per-stage spans, tokens and cost, `assistant` dashboard in Grafana
- [x] Streaming with cancellation, timeouts, and fallback to plain search
- [x] `catalog` publishes `catalog.events` via outbox, and the assistant reindexes and invalidates the cache with no manual reindex
- [ ] Swap embeddings and LLM for Ollama (adapters are ready and tested against a fake HTTP server; still need to run with real Ollama and re-evaluate)
- [x] `assistant-worker` service in `docker-compose`
- [ ] `assistant-worker` job in Prometheus

## Phase 8: Platform
- [x] OpenTelemetry with traces crossing Kafka, Prometheus metrics (RED), and a Grafana dashboard
- [x] CI on GitHub Actions
- [x] `assistant` in observability and CI (CI covers all services, the library, the assistant, and the frontend)
- [ ] Azure (Terraform) and Kubernetes (Helm/k3d): postponed

## Platform: security, contracts, and saga (DONE)
- [x] `identity` service (argon2id, EdDSA JWT, JWKS, rotating refresh with reuse detection), roles and scopes
- [x] Gateway validates the token, strips identity headers from the client, and signs the identity for the services
- [x] Object-level authorization (owner's order) and multi-tenancy (merchant's ledger, stock, and orders), with BOLA and isolation tests
- [x] Event versioning: `schema_version`, per-version models, upcasters, golden files, and contract tests; `OrderCreated` v2
- [x] Batched retention of outbox, inbox, idempotency, and refresh tokens
- [x] Global saga timeout and late payment refunded idempotently and auditably
- [x] `docs/SECURITY.md` and `docs/EVENT-EVOLUTION.md`
- [x] Access token revocation (logout, refresh reuse, and deactivated account), mass sign-up and login limited per IP+email with progressive backoff, security headers and body size limit on the gateway, public `GET /stock` returning only `available`, assistant with the user's identity
- [ ] MFA and `HttpOnly` cookie via a BFF (see limitations in `docs/SECURITY.md`)
