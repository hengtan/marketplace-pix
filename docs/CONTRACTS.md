**English** | [Português (Brasil)](pt-BR/CONTRATOS.md)

# Project contracts

Single source of truth for events, APIs, ports, and seed data. Whoever implements a service follows this
document. If something needs to change, record the change in the final report instead of editing this file.

## 1. Contribution rules

- Small, focused commits with English messages in the imperative mood, one logical change each.
- Code in English, with no unnecessary comments. Names carry the meaning.
- User-facing copy is correct Brazilian Portuguese (accents, agreement). The storefront targets Brazil, so the UI language stays pt-BR while code and documentation are English.
- Every change ships with its tests (see the Patterns section of `docs/ARCHITECTURE.md` and the README for the test strategy). Contracts in this file are the single source of truth: change them here first, then the code.

## 2. Ports

| Service | Host port | Container |
|---|---|---|
| gateway | 8000 | `gateway` |
| ordering | 8001 | `ordering-api` |
| payments | 8002 | `payments-api` |
| catalog | 8003 | `catalog-api` |
| inventory | 8004 | `inventory-api` |
| ledger | 8005 | `ledger-api` |
| notifications | 8006 | `notifications-api` |
| assistant | 8007 | `assistant-api` |
| identity | 8008 | `identity-api` |
| frontend (dev) | 5173 | n/a |
| Mailpit (SMTP / UI) | 1025 / 8025 | `mailpit` |

Infra already running (use it in integration tests): Postgres `localhost:5433` (user and password in the root `.env`),
Kafka `localhost:9094`, Redis `localhost:6380`. Existing databases: `ordering`, `payments`, `ledger`, `inventory`,
`catalog`, `notifications`, `identity`. Each service accesses only its own database and uses `<service>_test` in tests.
The `.env` is git-ignored. In a fresh clone run `scripts/up.sh`, which creates it with generated secrets; in an additional worktree copy it from your main checkout.

## 3. Python service pattern

Copy the structure and conventions of `backend/services/payments` (and `ordering`): Python 3.13, `uv`, FastAPI,
SQLAlchemy 2 async, Alembic, Pydantic v2, aiokafka, pytest + pytest-asyncio, `ruff` (line length 100), `mypy --strict`.

- Layers: `domain` (pure) → `application` (use cases + ports) → `infrastructure` → `interface`.
- Each use case runs in a Unit of Work (one transaction).
- Event producer: **outbox** (`outbox_events` table, partial index) + relay (`relay_main.py`).
- Event consumer: **inbox** (`inbox_messages`, PK `(message_id, consumer)`), manual offset commit,
  `KafkaEventConsumer` from `payments/infrastructure/messaging/kafka_consumer.py`.
- Entry points: `main.py` (API), `worker_main.py` (consumers and jobs), `relay_main.py` (outbox).
- Config via `pydantic-settings` (environment variables, root `.env` when present) with `load_settings()`.
- `GET /health` and `GET /ready` on every API. Multi-stage Dockerfile identical to the one in `payments`.
- Tests: unit tests with fakes (which only take effect on `commit` and clear the event buffer on persist) and
  integration tests against real Postgres, Kafka, and Redis, always in a `<service>_test` database and with randomly named topics.
- Every relevant failure case (duplicates, concurrency, a crash midway) has a test.

## 4. Events (Kafka)

Message: key = `order_id` (text), value = JSON, headers `event_id` (uuid), `event_type`, and `schema_version`.
The same `schema_version` (integer) is also carried inside the JSON. A message without the version counts as `1`.
Consumers deduplicate by `event_id` (inbox) and ignore types they do not handle. Dates in ISO 8601 UTC.

Versioning (details in `docs/EVENT-EVOLUTION.md`): each type has one pydantic model per version in
`marketplace_common.events`, with upcasters between adjacent versions. Rules: a compatible change (a new
**optional** field) bumps the version, and consumers ignore fields they do not know; an incompatible change
(removing, renaming, changing a type or its semantics) becomes a new type. Each producer has a contract test
against the library's golden files (`marketplace_common/events/golden/`), which fails if the payload drifts from the agreement.
Consumer group = service name (if a service has more than one consumer, add a suffix: `ledger-orders`).

### orders.events (producer: ordering)

| Event | Fields |
|---|---|
| `OrderCreated` (v2) | `order_id`, `customer_id`, `customer_name`, `customer_email`, `total_cents`, `currency`, `items[]` with `product_id`, `merchant_id`, `quantity`, `unit_price_cents`, `customer_type` (`guest` or `registered`, optional, new in v2); plus `event_id`, `occurred_at`, `schema_version`. v1 is identical, without `customer_type` |
| `OrderPaid` | `order_id`, `event_id`, `occurred_at` |
| `OrderCancelled` | `order_id`, `reason`, `event_id`, `occurred_at` |
| `PaymentRefundRequested` | `order_id`, `payment_id`, `amount_cents`, `currency`, `reason`, `event_id`, `occurred_at`, `schema_version` |

Values of `OrderCancelled.reason`: `payment expired`, `out of stock`, and `saga timeout` (an order stuck in
PENDING beyond the saga deadline, `SAGA_TIMEOUT_SECONDS`, default 2700). `PaymentRefundRequested` is emitted when a
payment is confirmed for an order that was already cancelled (late payment).

### payments.events (producer: payments)

| Event | Fields |
|---|---|
| `PaymentCreated` | `order_id`, `payment_id`, `amount_cents`, `currency`, `pix_code`, `expires_at` |
| `PaymentConfirmed` | `order_id`, `payment_id`, `amount_cents`, `currency` |
| `PaymentExpired` | `order_id`, `payment_id` |
| `PaymentCancelled` | `order_id`, `payment_id` |
| `PaymentRefunded` | `order_id`, `payment_id`, `amount_cents`, `currency`, `reason` |

### inventory.events (producer: inventory)

| Event | Fields |
|---|---|
| `StockReserved` | `order_id` |
| `StockRejected` | `order_id`, `reason`, `missing[]` with `product_id`, `requested`, `available` |
| `StockCommitted` | `order_id` |
| `StockReleased` | `order_id`, `reason` |

### ledger.events (producer: ledger)

| Event | Fields |
|---|---|
| `LedgerTransactionPosted` | `order_id`, `transaction_id`, `total_cents`, `platform_fee_cents` |
| `LedgerTransactionReversed` | `order_id`, `transaction_id`, `total_cents`, `platform_fee_cents` (reversal of an already posted payment) |

### catalog.events (producer: catalog)

Key = `product_id` (text). Published by the catalog's outbox (`catalog-relay`), in the same transaction as the write.
They have no `order_id`: the `event_type` header and `schema_version` follow the general rule. The `catalog.events`
and `catalog.events.dlq` topics are created in `kafka-init`.

| Event | Fields | When |
|---|---|---|
| `ProductCreated` (v1) | `product_id`, `merchant_id`, `slug`, `name`, `category`, `price_cents`, `currency`, `event_id`, `occurred_at`, `schema_version` | new product (clears the cache that depends on filters and on "not found") |
| `ProductUpdated` (v1) | the same fields as `ProductCreated` (a snapshot of the product) | name, description, category, image, or tags changed |
| `ProductPriceChanged` (v1) | `product_id`, `merchant_id`, `old_price_cents`, `new_price_cents`, `currency`, `event_id`, `occurred_at`, `schema_version` | price changed (invalidates answers that mention the product); a price edit and a text edit in the same call produce both events |
| `ProductDeactivated` (v1) | `product_id`, `merchant_id`, `event_id`, `occurred_at`, `schema_version` | product left the catalog (it disappears from listings and a new order is refused) |

An edit with no actual change (same values) publishes nothing. The `assistant` also accepts the legacy type
`ProductDeleted` as a synonym for `ProductDeactivated`.

### Who consumes what

| Service | Consumes | Reacts |
|---|---|---|
| payments | `OrderCreated`, `OrderCancelled`, `PaymentRefundRequested` | creates a charge; cancels a pending charge; refunds a confirmed payment at the PSP |
| ordering | `PaymentConfirmed`, `PaymentExpired`, `StockRejected` | marks paid; cancels (`payment expired`); cancels (`out of stock`); if the order was already cancelled, audits and requests a refund |
| inventory | `OrderCreated`, `PaymentConfirmed`, `PaymentExpired`, `PaymentCancelled`, `PaymentRefunded`, `OrderCancelled`, `ProductCreated`, `ProductDeactivated` (from `catalog.events`, group `inventory-catalog`) | reserves; commits the sale; releases; returns the refunded sale to stock; creates the stock row for the new product with `available=0` and the owning `merchant_id` (or adopts the owner of an ownerless row; `ProductCreated` also reactivates a deactivated row); `ProductDeactivated` removes the row from the merchant's list (`GET /stock/mine`) without deleting the quantity. It never replaces an existing owner or touches the quantity |
| ledger | `OrderCreated`, `PaymentConfirmed`, `PaymentRefunded` | keeps the order projection; posts the transaction; posts the reversal |
| notifications | `OrderCreated`, `PaymentCreated`, `OrderPaid`, `OrderCancelled` | sends emails (Celery) |
| assistant | `ProductCreated`, `ProductUpdated`, `ProductPriceChanged`, `ProductDeactivated` (from `catalog.events`) | reindexes only what changed and invalidates cached answers (`python -m assistant.worker_main`, group `assistant`) |

## 5. REST APIs (all behind the gateway)

The frontend talks **only** to the gateway, at `http://localhost:8000`. The tables below show the path on the
gateway and the real path on the service. The gateway implements exactly these rewrite rules:

- `/api/catalog/<rest>` → catalog `/<rest>`
- `/api/inventory/<rest>` → inventory `/<rest>`
- `/api/ledger/<rest>` → ledger `/<rest>`
- `/api/orders` and `/api/orders/<rest>` → ordering `/orders` and `/orders/<rest>`
- `/api/payments/by-order/<rest>` → payments `/payments/by-order/<rest>`
- `/api/payments/dev/<rest>` → payments `/dev/<rest>`
- `/api/notifications` and `/api/notifications/<rest>` → notifications `/notifications` and `/notifications/<rest>`
- `/api/assistant/<rest>` → assistant `/<rest>`
- `/api/auth/<rest>` → identity `/auth/<rest>`
- `GET /api/health` → aggregates the `/health` of every service

Paginated lists: `{ "items": [...], "total": 0, "page": 1, "page_size": 20 }`. Money is always in integer cents
(`*_cents`) with `currency` ("BRL"). IDs are uuids. Errors: `{ "detail": "text" }`.

### catalog (port 8003)

| Gateway | Service |
|---|---|
| `GET /api/catalog/products` | `GET /products` |
| `GET /api/catalog/products/{id}` | `GET /products/{id}` |
| `GET /api/catalog/products/slug/{slug}` | `GET /products/slug/{slug}` |
| `GET /api/catalog/products/by-ids?ids=a,b` | `GET /products/by-ids?ids=a,b` |
| `GET /api/catalog/categories` | `GET /categories` |
| `POST /api/catalog/products` | `POST /products` (merchant on their own catalog; `admin` supplies `merchant_id`) |
| `PATCH /api/catalog/products/{id}` | `PATCH /products/{id}` |
| `DELETE /api/catalog/products/{id}` | `DELETE /products/{id}` (deactivates; idempotent, `204`) |
| `POST /api/catalog/products/{id}/reactivate` | `POST /products/{id}/reactivate` (owner or `admin`; returns the product; reactivating an active product is a no-op `200`; publishes `ProductCreated` again so consumers reindex it and ensure stock) |
| `GET /api/catalog/products/mine?merchant_id=` | `GET /products/mine` (requires the catalog write scope; a merchant gets their own products, **including deactivated ones**, each with `active`; `admin` must supply `merchant_id`, otherwise `422`; `Cache-Control: no-store`) |

Catalog reads (`GET`) return `ETag` and `Cache-Control: public, max-age=0, must-revalidate`: the browser always revalidates and gets `304` when nothing changed, so a merchant edit (price, name, new product, deactivated product) is never stuck behind a cache. The TTL is configurable via `CACHE_MAX_AGE_SECONDS` (default `0`).

`GET /products` accepts `q`, `category`, `min_price_cents`, `max_price_cents`, `sort`
(`relevance|price_asc|price_desc|newest|rating`), `page`, `page_size` (default 12, maximum 48).

`GET /products/by-ids` returns the paginated envelope (`items`, `total`, `page`, `page_size`), in the requested order,
ignores unknown ids, and accepts at most 100 ids (422 if `ids` is missing or invalid). Out-of-range parameters
return 422 with a text `detail`.

Writes (require a token with `catalog:write:own` and ownership of the product, or `catalog:write:any`; `401` without an identity,
`403` on someone else's product): `POST` accepts `name`, `description`, `price_cents` (> 0), `category` (an existing slug), `slug`
(optional, derived from the name), `image_url`, `tags[]`, `merchant_id` (`admin` only) and returns `201` with the product, `409` if the
slug already exists; `PATCH` accepts `name`, `description`, `price_cents`, `category`, `image_url`, `tags` (at least one field,
`422` for unknown fields). A deactivated product disappears from all reads (`404`, absent from the list, from `by-ids`, and from the
category counts). Each write records the corresponding event in the outbox in the same transaction.

Product: `id`, `slug`, `name`, `description`, `price_cents`, `currency`, `category`, `image_url` (may be null),
`rating` (0 to 5), `reviews_count`, `tags[]`, `merchant` (`id`, `slug`, `name`), `created_at`.
Category: `slug`, `label`, `count`.

### inventory (port 8004)

| Gateway | Service |
|---|---|
| `GET /api/inventory/stock?product_ids=a,b` | `GET /stock?product_ids=a,b` → `[{product_id, available}]` |
| `GET /api/inventory/stock/{product_id}` | `GET /stock/{product_id}` |
| `PUT /api/inventory/stock/{product_id}` | `PUT /stock/{product_id}` with `{ "available": 10 }` (a merchant only on their own products, `403` on the rest; `admin` on all) |
| `GET /api/inventory/stock/mine` | `GET /stock/mine` → stock of the token merchant's products, with `reserved` |

Stock reads are public and return only `available`: `reserved` (in-flight demand) appears only to the merchant who owns the
product (scope `stock:write:own` and a `merchant_id` equal to the product's) and to `admin`, in `GET /stock`, `GET /stock/{id}`,
`GET /stock/mine`, and in the `PUT` response. To make this work, the gateway forwards the signed identity when the token is valid on stock
reads; a missing, invalid, or expired token on these routes counts as anonymous (the storefront stays public). A product with no owning
merchant never exposes `reserved` to a merchant.

### ordering (port 8001)

| Gateway | Service |
|---|---|
| `POST /api/orders` | `POST /orders` (`Idempotency-Key` header required) |
| `GET /api/orders/{id}` | `GET /orders/{id}` |
| `GET /api/orders?customer_id=&page=&page_size=` | `GET /orders?...` |
| `GET /api/orders/merchant?page=&page_size=` | `GET /orders/merchant?...` |

`POST` body: `customer_id` (required only for guest checkout; with a token the `sub` applies and a different
value gives `403`), `customer_name`, `customer_email`, `items[]` with `product_id` and `quantity`.
Object-level authorization: an order placed with a token belongs to the user (`owner_id`); `GET /orders/{id}` on
someone else's order responds `404` (same as nonexistent), `GET /orders` lists only the token's own (another
person's `customer_id` gives `403`; `admin` may query anyone). A guest order is read by whoever has the id and
listed by `customer_id` without a token, and never appears in a user's account. `GET /orders/merchant` returns only
the orders that contain items from the token's merchant, with only their items: `id`, `status`, `currency`, `created_at`,
`customer_name`, `subtotal_cents`, `items[]` (no customer email).
**The price and `merchant_id` come from the catalog**, never from the client. `201` response: `{ "id": "..." }`.
Order: `id`, `customer_id`, `customer_name`, `customer_email`, `status` (`PENDING|PAID|CANCELLED`), `currency`,
`total_cents`, `created_at`, `cancel_reason` (null), `items[]` (`product_id`, `merchant_id`, `quantity`, `unit_price_cents`).

### payments (port 8002)

`GET /api/payments/by-order/{id}` responds only to someone who can see the order (the gateway first queries ordering with
the caller's identity; `404` otherwise).

Right after the order is created the charge does not exist yet (it is born from the `OrderCreated` event). While the order exists and belongs to the
caller and the charge has not been created yet, `GET /api/payments/by-order/{id}` responds `202` with `Retry-After: 1` and body
`{ "detail": "payment is being created", "retry_after_seconds": 1 }` (without the payment fields: whoever receives `202` must try
again). `404` only when the order does not exist or does not belong to the caller.

| Gateway | Service |
|---|---|
| `GET /api/payments/by-order/{order_id}` | `GET /payments/by-order/{order_id}` |
| `POST /api/payments/dev/psp/charges/{charge_id}/pay` | `POST /dev/psp/charges/{charge_id}/pay` (development only) |

Payment: `id`, `order_id`, `status` (`PENDING|CONFIRMED|EXPIRED|CANCELLED|REFUNDED`), `amount_cents`, `currency`,
`pix_code`, `psp_charge_id`, `expires_at`, `confirmed_at`.

### ledger (port 8005)

All routes require a token. A merchant sees only their own `merchant_id` and their own `merchant:<id>` account
(`403` on the others, including `platform:revenue` and `psp:receivable`); `admin` sees everything.

| Gateway | Service |
|---|---|
| `GET /api/ledger/merchants/{merchant_id}/summary?days=30` | `GET /merchants/{merchant_id}/summary?days=30` |
| `GET /api/ledger/accounts/{account_id}/entries?page=&page_size=` | `GET /accounts/{account_id}/entries?...` |
| `GET /api/ledger/reconciliation` | `GET /reconciliation` |

Merchant summary: `merchant_id`, `currency`, `balance_cents` (receivable), `gross_sales_cents`,
`platform_fees_cents`, `net_sales_cents`, `orders_count`, `daily[]` (`date`, `gross_cents`, `net_cents`, `orders`).
Accounts: `merchant:<merchant_id>`, `platform:revenue`, `psp:receivable`. Entry: `id`, `transaction_id`,
`direction` (`DEBIT|CREDIT`), `amount_cents`, `description`, `order_id`, `created_at`.
Reconciliation: `balanced` (sum of debits equals sum of credits), `total_debits_cents`, `total_credits_cents`,
`transactions_count`, `checked_at`.
Split rule: a platform fee of 10% (1000 bps) on each merchant's subtotal, rounded to the nearest
cent; the merchant receives the rest. In every transaction, debits = credits.

### notifications (port 8006)

Requires a token. The gateway rewrites `customer_id` with the token's `sub` (`403` if another one is sent; `admin` chooses).
Since a guest has no token, a guest cannot list notifications.

| Gateway | Service |
|---|---|
| `GET /api/notifications?customer_id=&page=&page_size=` | `GET /notifications?...` |
| `GET /api/notifications/{id}/preview` | `GET /notifications/{id}/preview` (HTML) |

Notification: `id`, `kind` (`ORDER_CREATED|PIX_READY|ORDER_PAID|ORDER_CANCELLED`), `subject`, `status`
(`QUEUED|SENT|FAILED`), `order_id`, `created_at`, `sent_at`.

### assistant (port 8007)

Shopping assistant with RAG and an agent with tools. **The entire "model" is simulated by default**
(`EMBEDDER=hashing`, `LLM=mock`), with ports and adapters to swap in Ollama later. Database `assistant` on the
pgvector instance: `localhost:5434` on the host, `pgvector:5432` on the Docker network (user and password from `.env`).

| Gateway | Service |
|---|---|
| `POST /api/assistant/chat` | `POST /chat` |
| `POST /api/assistant/chat/stream` | `POST /chat/stream` (SSE) |
| `GET /api/assistant/sessions/{id}` | `GET /sessions/{id}` |
| `POST /api/assistant/admin/reindex` | `POST /admin/reindex` |
| `GET /api/assistant/evals/latest` | `GET /evals/latest` |
| `GET /api/assistant/cache/stats` | `GET /cache/stats` |

`POST /chat` body: `session_id` (optional), `message` (1 to 1000 characters). With a token, the gateway forwards the
signed identity (the same one used for the other services, verified with `INTERNAL_AUTH_SECRET`): the daily budget applies
per user and `get_order_status` queries ordering **as that user**, so an account sees only its own orders
(someone else's order answers "not found", same as a nonexistent one). Without a token (guest) the order is queried by id only,
as in ordering. Identity headers without a valid signature count as anonymous. The legacy `X-User-Id` header
without a signature still identifies the budget (without it the IP applies) but grants access to no order. Response: `session_id`, `answer`,
`citations[]` (`product_id`, `slug`, `name`, `score`), `tool_calls[]` (`name`, `arguments`, `result_summary`,
`duration_ms`), `retrieved[]` (the retrieved passages with `score`), `latency_ms` and, new and optional,
`cached` (the answer came from the semantic cache), `degraded` and `warning` (the model failed or timed out and the
answer carries only the search results). Without enough context the answer says it found nothing instead of
making something up; an out-of-scope question gets "Só consigo ajudar com produtos..." ("I can only help with products...") without calling a tool; a prompt injection
attempt gets "Não posso seguir esse tipo de instrução" ("I can't follow that kind of instruction") without calling the agent or the model.

`POST /chat/stream` emits SSE events `tool_call`, `token`, and `done` (as before) and two new ones that old clients
can ignore: `warning` (`detail`, `reason`, right before a degraded `done`) and `error` (`detail`; today
`model unavailable` and `budget exceeded` with `scope`). Closing the connection cancels generation and frees the model.

Budget: exceeding the session's or the user's token or cost limit for the day returns **429** with `detail`
`budget exceeded`, `scope` (`session` or `user`), `limit` (`tokens` or `cost`), and `Retry-After`.

`GET /cache/stats`: `enabled`, `entries`, `persisted_hits`, `persisted_tokens_saved` (from the database), `lookups`, `hits`,
`misses`, `skips`, `hit_rate`, `tokens_saved`, `cost_saved_usd` (from the process, since it started).
`POST /admin/reindex` gained `flagged` (products whose text had injection phrases stripped).

Agent tools (they call the other services over HTTP): `search_products`, `get_stock`
(inventory), `get_order_status` (ordering), and `get_policy` (fixed answers about returns, delivery, payment,
cancellation, and warranty). The full pipeline, with measured numbers, is in `docs/RAG-EXPLAINED.md` and
`docs/RAG-EVALUATION.md`.

### gateway (port 8000)

FastAPI reverse proxy. Routes `/api/<service>/...` to the service, forwards the method, body, query, and relevant
headers (including `Idempotency-Key`), creates `X-Request-Id`, applies CORS for `http://localhost:5173`, and
aggregates `GET /api/health` (with each service's circuit breaker state in `breakers`).

Resilience (details in `docs/RESILIENCE.md`):

- Distributed request limit (Redis), per client and per route. Every response carries `RateLimit-Limit`,
  `RateLimit-Remaining`, and `RateLimit-Reset`; the `429` carries `Retry-After`.
- `X-Request-Deadline`: the request's remaining time in milliseconds. The gateway accepts the client's (capped at
  30 s), uses 8 s by default (25 s for the assistant), and forwards what is left to the services.
- A service with an open circuit or a full bulkhead responds `503` with `Retry-After` and body
  `{ "detail": "...", "code": "circuit_open" | "overloaded", "service": "catalog", "retry_after_seconds": 10 }`.
  A blown deadline responds `504`. The `detail` field remains the usual text.
- Only `GET` and `HEAD` are retried by the gateway (exponential backoff with jitter and a retry budget).
- Every gateway response (including `401`, `413`, `429`, `5xx`, and CORS preflight) carries `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, a restrictive `Permissions-Policy`, and `Cross-Origin-Resource-Policy: same-site` (whatever the
  service sends under these names is overwritten). `Strict-Transport-Security` only with `HSTS_ENABLED=true` (off in development).
- A request body above `MAX_REQUEST_BODY_BYTES` (1 MiB by default) responds `413` with `{ "detail": "request body too large" }`,
  decided by `Content-Length` or, for a body with no declared size, when the running total passes the limit; the service is not called.
- The client is identified by the connection IP or, only when the connection comes from a proxy listed in `TRUSTED_PROXIES` (comma-separated
  CIDRs), by the first untrusted address in `X-Forwarded-For` read from right to left (`X-Real-IP` if it is missing).
  The service receives `X-Forwarded-For` with the resolved address.

### identity (port 8008): authentication and authorization

Decision and rationale in `docs/adr/0001-identity-as-a-service.md`. The frontend talks only to `/api/auth/*`.

| Gateway | Access | Body and response |
|---|---|---|
| `POST /api/auth/register` | anonymous | `{ email, name, password }` → `201` with tokens (always creates a `customer`) |
| `POST /api/auth/login` | anonymous | `{ email, password }` → `200` with tokens |
| `POST /api/auth/refresh` | anonymous | `{ refresh_token }` → `200` with new tokens (the old one dies) |
| `POST /api/auth/logout` | anonymous | `{ refresh_token }` → `204` (revokes the session and its access tokens, which start receiving `401` within 1 s; idempotent) |
| `GET /api/auth/me` | token | profile of the token's user |
| `POST /api/auth/admin/users` | `admin` | `{ email, name, password, roles[], merchant_id or merchant_slug }` → `201` (creates a merchant or an admin) |

Response of `register`, `login`, and `refresh`: `access_token` (JWT), `refresh_token` (opaque), `token_type`
(`Bearer`), `expires_in` (seconds, 600), and `user` (`id`, `email`, `name`, `roles[]`, `merchant_id`). Errors:
`401 invalid credentials` (the same response for an unknown email, a wrong password, a locked account, or a
deactivated one), `401 invalid refresh token`, `409 email already registered`, `422` (email or password outside the
policy: minimum 10 characters), `429` (attempt limit, below). Token responses carry `Cache-Control: no-store`.

Protection against mass sign-up and password guessing (`register` and `login`): a distributed limit (token bucket on Redis,
shared across instances) per **IP + email** (default: 10 logins per minute, 5 sign-ups per hour) and per **IP** (60 logins per
minute, 30 sign-ups per hour, for anyone who changes the email on every attempt), plus a progressive backoff per IP + email: each consecutive failure
(wrong password, email already registered, password outside the policy) doubles the lockout (2 s, 4 s, 8 s... up to 15 min) and a successful
login resets it. Whoever exceeds the limit receives `429` with `Retry-After` and body `{ "detail": "too many attempts", "retry_after_seconds": N }`.
The IP is the one the gateway forwards in `X-Forwarded-For`, accepted only from a proxy listed in `TRUSTED_PROXIES`; the email enters the keys only as a hash.

Access token revocation: logout, refresh reuse detection, and a deactivated account put the `jti` of the session's
still-live access tokens on a list in Redis (TTL = the token's remaining lifetime, plus 10 s of slack). The gateway checks the list
(0.5 s cache) and responds `401` to a revoked token. With Redis down, `REVOCATION_FAIL_OPEN=true` (default) accepts the token
(it still expires on its own in 10 min) and `false` responds `503` to anyone with a token.

Frontend usage:

1. Keep `access_token` in memory and send `Authorization: Bearer <token>` on every authenticated call.
2. Store the `refresh_token` (ideally in an `HttpOnly` cookie once there is a BFF; in this study project, `sessionStorage`).
3. On a `401` with a token that should be valid, call `/api/auth/refresh` **exactly once** and repeat the
   call. If the refresh also gives `401`, the session is over: go back to login. Never reuse an old refresh token
   (presenting an already-used token revokes the whole session on both devices).
4. The `access_token` is an `EdDSA` JWT with `jti` and `sid`; the claims useful to the UI are `roles`, `scope`, and `merchant_id`
   (decode them to display, never to decide security: the server revalidates everything).
5. `Authorization` must be in `Access-Control-Allow-Headers` (the gateway already allows it).

Roles and scopes:

| Role | Scopes |
|---|---|
| `customer` | `orders:create`, `orders:read:own`, `notifications:read:own` |
| `merchant` | those of `customer` plus `orders:read:merchant`, `stock:write:own`, `catalog:write:own`, `ledger:read:own` (and `merchant_id` in the token) |
| `admin` | those of `customer` plus `orders:read:any`, `orders:read:merchant`, `stock:write:any`, `catalog:write:any`, `ledger:read:any`, `ledger:reconcile`, `users:manage`, `assistant:admin` |

Development accounts (created by `identity-seed` when `IDENTITY_SEED_PASSWORD` exists in `.env`; the
password is that secret): `admin@marketplace-pix.local` (admin) and one merchant per store,
`aurora-tech@marketplace-pix.local`, `casa-lume@marketplace-pix.local`, and `trilha-sports@marketplace-pix.local`.
The merchant's `merchant_id` is the one from the seed in section 6.

Access matrix on the gateway (`401` without a valid token, `403` without the scope):

| Route | Access |
|---|---|
| `GET /api/catalog/**` | public |
| `GET /api/inventory/stock**` | public (with a valid token the gateway forwards the identity, so the owning merchant sees `reserved`) |
| `POST /api/orders` | anonymous (guest) or authenticated; `ALLOW_GUEST_CHECKOUT=false` requires a token |
| `GET /api/orders`, `GET /api/orders/{id}`, `GET /api/payments/by-order/{id}` | anonymous or authenticated; the service decides by owner |
| `GET /api/orders/merchant` | `orders:read:merchant` |
| `PUT /api/inventory/stock/{id}`, `GET /api/inventory/stock/mine` | `stock:write:own` or `stock:write:any` |
| `POST /api/catalog/products`, `PATCH\|DELETE /api/catalog/products/{id}`, `POST /api/catalog/products/{id}/reactivate`, `GET /api/catalog/products/mine` | `catalog:write:own` or `catalog:write:any` (the service checks the owner) |
| `GET /api/ledger/**` | `ledger:read:own` or `ledger:read:any` (the service checks the merchant) |
| `GET /api/ledger/reconciliation` | `ledger:reconcile` |
| `GET /api/notifications**` | `notifications:read:own` (the gateway forces `customer_id` from the token; `admin` may choose) |
| `POST /api/payments/dev/**` | optional (a guest also simulates their own PIX; it exists only with `ENABLE_DEV_ROUTES`, in production it is `404`) |
| `POST /api/assistant/admin/**` | `assistant:admin` |
| `GET\|POST /api/assistant/**` | anonymous or authenticated |

Identity for the services (not a frontend contract): the gateway removes `Authorization` and any
`X-User-Id`, `X-User-Roles`, `X-User-Scopes`, `X-Merchant-Id`, `X-Auth-Ts`, and `X-Auth-Sig` coming from the client and,
with a valid token, injects these headers signed with `INTERNAL_AUTH_SECRET` (HMAC-SHA256 over user,
roles, scopes, merchant, timestamp, and `X-Request-Id`, valid for 60 s). A service without the correct signature treats the
call as anonymous.

## 6. Seed data (deterministic)

`merchant_id = uuid5(NAMESPACE_URL, "marketplace-pix:merchant:<slug>")`
`product_id  = uuid5(NAMESPACE_URL, "marketplace-pix:product:<slug>")`

Merchants: `aurora-tech` (Aurora Tech), `casa-lume` (Casa Lume), `trilha-sports` (Trilha Sports).

Product names, categories, and labels are product data in Brazilian Portuguese and are kept as is (the storefront UI is in Portuguese).

| Slug | Name | Category | Merchant | Price (cents) |
|---|---|---|---|---|
| fone-bluetooth-nova | Fone Bluetooth Nova ANC | tecnologia | aurora-tech | 34990 |
| caixa-som-pulse | Caixa de Som Pulse 360 | tecnologia | aurora-tech | 21990 |
| smartwatch-orbit | Smartwatch Orbit S2 | tecnologia | aurora-tech | 49990 |
| teclado-mecanico-forge | Teclado Mecânico Forge 75% | tecnologia | aurora-tech | 38990 |
| mouse-glide-pro | Mouse sem fio Glide Pro | tecnologia | aurora-tech | 17990 |
| webcam-clear-4k | Webcam Clear 4K | tecnologia | aurora-tech | 25990 |
| carregador-turbo-65w | Carregador Turbo 65W GaN | tecnologia | aurora-tech | 12990 |
| hub-usbc-dock | Hub USB-C Dock 8 em 1 | tecnologia | aurora-tech | 15990 |
| luminaria-arco-dourado | Luminária Arco Dourado | casa | casa-lume | 28990 |
| cafeteira-prensa-francesa | Cafeteira Prensa Francesa | casa | casa-lume | 14990 |
| vaso-ceramica-terra | Vaso de Cerâmica Terra | casa | casa-lume | 8990 |
| manta-algodao-nuvem | Manta de Algodão Nuvem | casa | casa-lume | 19990 |
| jogo-facas-chef | Jogo de Facas Chef | casa | casa-lume | 32990 |
| difusor-aromas-calma | Difusor de Aromas Calma | casa | casa-lume | 11990 |
| relogio-parede-minimal | Relógio de Parede Minimal | casa | casa-lume | 9990 |
| organizador-bambu-set | Organizador de Bambu Set | casa | casa-lume | 7990 |
| tenis-corrida-vento | Tênis de Corrida Vento | esporte | trilha-sports | 45990 |
| mochila-trilha-30l | Mochila de Trilha 30L | esporte | trilha-sports | 31990 |
| garrafa-termica-aco-750 | Garrafa Térmica Aço 750 ml | esporte | trilha-sports | 9990 |
| tapete-yoga-grip | Tapete de Yoga Grip | esporte | trilha-sports | 12990 |
| relogio-gps-trail | Relógio GPS Trail | esporte | trilha-sports | 64990 |
| capacete-bike-aero | Capacete de Bike Aero | esporte | trilha-sports | 27990 |
| corda-pular-speed | Corda de Pular Speed | esporte | trilha-sports | 4990 |
| kit-elasticos-forca | Kit de Elásticos de Força | esporte | trilha-sports | 6990 |

Categories (`slug` → `label`): `tecnologia` → Tecnologia, `casa` → Casa e decoração, `esporte` → Esporte e aventura.
Initial stock (inventory): 25 units per product, except `relogio-gps-trail` with 3 and `smartwatch-orbit` with 5
(to exercise the "last units" warning and the insufficient-stock case).
Images: the catalog stores a verified `image_url` (HTTP 200) or null; the frontend must degrade gracefully.
