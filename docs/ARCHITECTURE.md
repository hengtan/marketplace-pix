**English** | [Português (Brasil)](pt-BR/ARQUITETURA.md)

# Architecture

## Overview

Microservices, each with its own database, asynchronous communication through events (Kafka), and a saga
orchestrated by `ordering`. Synchronous calls happen only at the edge (gateway to service) and for simple queries.

## Purchase flow

1. `POST /orders` (with `Idempotency-Key`): ordering writes the order as `PENDING` and the `OrderCreated` event to the outbox, in the same transaction. It responds 202.
2. The relay publishes `OrderCreated`. Inventory reserves stock (with a TTL) and publishes `StockReserved`.
3. Ordering requests the charge. Payments generates the PIX (QR code and copy-and-paste code, with an expiration) and publishes `PaymentRequested`. (PIX is Brazil's instant payment system.)
4. The PSP (payment service provider) calls the webhook. Payments validates the signature AND queries the charge at the PSP before confirming. It publishes `PaymentConfirmed`.
5. The ledger posts the entries (customer, platform, merchant). Ordering marks the order `PAID`. Notifications alerts the customer.
6. Failure or expiration: the saga compensates (releases stock, cancels the charge, marks the order `CANCELLED`).

## Saga: global timeout and late payment

Ordering runs a **process manager** (`SagaTimeoutManager`, in `worker_main`) that sweeps orders stuck in
`PENDING` beyond `SAGA_TIMEOUT_SECONDS` (default 2700, above the PIX TTL). Each stuck order is cancelled with
`saga timeout`, becomes a row in `order_audit`, and emits `OrderCancelled`. The compensations are reactions to
that event, all idempotent: payments cancels the charge at the PSP and inventory releases the reservation.

If a payment arrives **after** the cancellation (the PSP confirmed almost at the deadline), ordering does not
reopen the order: it records the anomaly in `order_audit` (unique key per order and payment) and emits
`PaymentRefundRequested`. Payments refunds at the PSP and emits `PaymentRefunded`, the ledger posts the reversal
(a `REVERSAL` transaction that zeroes out the accounts), and inventory puts back on the shelf the sale that had
already been committed. Every step has an inbox, and the outcome is the same whether a message is repeated or
arrives out of order.

```
order PENDING ──(deadline)──► CANCELLED + order_audit(SAGA_TIMEOUT) + OrderCancelled
                                   ├─► payments: cancels the charge
                                   └─► inventory: releases the reservation
PaymentConfirmed (late) ─► ordering: order_audit(LATE_PAYMENT) + PaymentRefundRequested
                                   └─► payments: refunds at the PSP ─► PaymentRefunded
                                          ├─► ledger: reversal (REVERSAL)
                                          └─► inventory: returns the sold stock
```

End-to-end verification with a short deadline: `scripts/e2e-saga.sh`.

## Kafka and Celery: separate roles

- Kafka: domain events (facts). Topics `orders.events`, `payments.events`, `inventory.events`, `ledger.events` (key `order_id`, ordered per order) and `catalog.events` (key `product_id`), all with 3 partitions and a `.dlq`. Each service is a consumer group.
- Celery with Redis as the broker: tasks (email, daily reconciliation).
- Kafka delivers at least once and rebalancing reprocesses messages, so the inbox is mandatory. Retry and DLQ use `*.retry` and `*.dlq` topics, implemented in-house.

## Catalog, assistant index, and semantic cache

The `catalog` is no longer read-only: the owning merchant (or the admin) creates, updates, and deactivates
products (`POST|PATCH|DELETE /products`). Each write records the event (`ProductCreated`, `ProductUpdated`,
`ProductPriceChanged`, `ProductDeactivated`) in the outbox, in the same transaction, and `catalog-relay`
publishes it to `catalog.events`. The `assistant-worker` consumes it, reindexes only what changed, and
invalidates the semantic cache for answers that mention the product: changing a price changes the chat answer
within seconds, with no manual reindex (verified in `scripts/e2e.sh`, section 11).

## User identity in the chat

The gateway signs the authenticated user's identity for the `assistant`, which verifies it with the same
`PrincipalResolver` from the library and forwards it (re-signed, with the same `X-Request-Id`) to `ordering`
when the `get_order_status` tool runs. Owners can see their own order through the chat, other users cannot, and
guests can still look up an order by id.

## Gateway edge

Before routing, the gateway caps the body size (`413`), resolves the real client IP (`X-Forwarded-For` only from
a proxy in `TRUSTED_PROXIES`), applies the rate limit, validates the JWT, and checks the list of revoked `jti`
values in Redis; every response goes out with the security headers. Paying for an order that exists but does not
have a charge yet responds `202` with `Retry-After`. Details in `docs/SECURITY.md` and `docs/RESILIENCE.md`.

## Patterns

| Pattern | Where | Rule |
|---|---|---|
| Unit of Work | every use case | one transaction per use case |
| Outbox | event producer | event written together with the data, relay publishes later |
| Inbox | event consumer | writes `message_id` before processing; a duplicate is ignored |
| HTTP idempotency | critical POSTs | `Idempotency-Key` stores the response of the first call |
| Saga (orchestration) | ordering | every step has a compensation; a timeout triggers compensation |
| Fail-closed | PIX webhook | when in doubt, the order stays pending |
| Circuit breaker, retry with budget, bulkhead | calls between services | one per dependency; retry on reads only (see `docs/RESILIENCE.md`) |
| Deadline propagation | gateway and services | `X-Request-Deadline` carries the remaining time; each hop caps its timeout to it |
| Distributed rate limit | gateway, identity | token bucket in Lua on Redis, per client and route (gateway) and per IP+email (sign-up and login), with an in-memory fallback |
| Progressive backoff | identity | each consecutive failure doubles the lockout per IP+email, in Redis |
| Revocation list | identity and gateway | `jti` of a revoked access token stored in Redis with TTL = remaining lifetime |

## Key tables

```sql
outbox_events(id, aggregate_id, type, payload jsonb, created_at, published_at NULL)
inbox_messages(message_id PK, consumer, processed_at)
idempotency_keys(key, request_hash, response jsonb, status, created_at)
ledger_entries(id, transaction_id, account_id, amount, direction)
```

## Clean Architecture per service

```
interface -> application -> domain
infrastructure -> application, domain
```

The `domain` is pure Python. The rule can be enforced in CI with `import-linter`.
Full DDD in ordering, payments, and ledger. Catalog and notifications can stay simple.

## Decisions

Record them in `docs/adr/` (one file per decision: context, decision, consequences).
