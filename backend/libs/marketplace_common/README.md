**English** | [Português (Brasil)](README.pt-BR.md)

# marketplace_common

Shared library for the marketplace microservices. It gathers what used to be copied into every service
(Kafka consumer with DLQ, publisher, outbox relay) and what cuts across all of them (observability and the
DLQ replay tool).

```
marketplace_common/
  messaging/       IncomingEvent, KafkaEventConsumer, KafkaPublisher, OutboxRelay, and the outbox ports
  observability/   JSON logs, tracing (OpenTelemetry), metrics (Prometheus), HTTP middlewares
  dlq/             python -m marketplace_common.dlq list | replay
  security/        Principal, roles and scopes, signed identity between gateway and services
  events/          versioned models per event, upcasters, golden files, and contract tests
  maintenance/     CleanupJob: batched retention for the published outbox, the inbox, and idempotency keys
```

Installation in the services, by path and editable (each service's `pyproject.toml`):

```toml
dependencies = ["marketplace-common[kafka,sqlalchemy]"]

[tool.uv.sources]
marketplace-common = { path = "../../libs/marketplace_common", editable = true }
```

The extras avoid pulling in dependencies a service does not use: the gateway installs only the core
(no `aiokafka` and no SQLAlchemy), while the others ask for `kafka` and `sqlalchemy`.

## 1. Observability

Observability is the ability to understand what is happening inside a system by looking only at what it
emits. Monitoring answers "is it broken?". Observability answers "why is it broken and where?", including
for questions nobody anticipated. It rests on three signals, and each one answers a different question.

| Signal | What it is | Question it answers | Cost | In this project |
|---|---|---|---|---|
| Logs | Discrete events, one line per fact | What happened at that moment? | High in volume | JSON on stdout, with `trace_id`, `span_id`, and `request_id` |
| Metrics | Numbers aggregated over time | How much, how often, is it getting worse? | Low and constant | Prometheus and Grafana |
| Traces | The path of a request across several services | Where was the time spent and where did it fail? | Medium (can be sampled) | OpenTelemetry and Jaeger |

The value shows up when the three are connected. A metric alert (errors went up) leads to the trace of a slow
request (the payments database span took a long time), and the `trace_id` printed in the log opens the exact
lines of that execution.

### Trace and span

- A **span** is a unit of work with a start, an end, a name, and attributes: an HTTP request, a SQL query, the
  handling of an event. It has a `span_id` and points to its parent (`parent_span_id`).
- A **trace** is the tree of spans for a single business operation, tied together by one `trace_id`. A created
  order becomes a trace that crosses ordering, payments, inventory, ledger, and notifications.
- **Context** is the (`trace_id`, `span_id`) pair that travels with the call. Over HTTP it goes in the
  `traceparent` header (W3C standard), `00-<trace_id>-<span_id>-01`. On Kafka it goes in the message headers,
  under the same name.

### The RED method

For any service that handles requests, three numbers are enough to tell whether it is healthy:

- **R**ate: how many requests per second.
- **E**rrors: how many fail (here, 5xx responses over the total).
- **D**uration: how long they take, always in percentiles (p50, p95, p99) and never by the mean alone.

Each API exposes `http_requests_total{method,route,status}` and `http_request_duration_seconds{method,route}`.
The `route` label uses the template (`/orders/{order_id}`), not the actual path, to avoid a cardinality
explosion in the series. Paths that match no route are recorded as `unmatched`. For workers, which do not serve
HTTP, the equivalent is the **USE** method (utilization, saturation, errors), represented here by handler
duration, the pending outbox, and the DLQ.

### What the library provides

| Piece | What it is for |
|---|---|
| `setup_logging(service)` | Replaces the logging handlers with a JSON formatter. Includes `trace_id` and `span_id` when a span is active and `request_id` when there is a request |
| `setup_tracing(service)` | Turns on OpenTelemetry from the `OTEL_*` variables. Without `OTEL_EXPORTER_OTLP_ENDPOINT` it does nothing (a safe no-op) |
| `install_api_observability(app, service)` | On a FastAPI API: logs, tracing, `X-Request-Id`, RED metrics, and the `GET /metrics` route |
| `setup_worker_observability(service)` | In workers and relays: logs, tracing, and a `/metrics` server on the `METRICS_PORT` port (default 9100) |
| `instrument_sqlalchemy(engine)` | Each query becomes a child span |
| `current_traceparent()` | The current context as text, used to store it in the outbox |

Automatic instrumentation: FastAPI (one span per request), httpx (calls between services, injects the
`traceparent`), and SQLAlchemy. The `/health`, `/ready`, and `/metrics` routes are left out of the traces.

Environment variables (OpenTelemetry standard):

| Variable | Effect |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Turns tracing on. E.g.: `http://jaeger:4318` (OTLP over HTTP) |
| `OTEL_SERVICE_NAME` | Overrides the service name the code reports |
| `OTEL_SDK_DISABLED=true` | Turns it off even when an endpoint is configured |
| `METRICS_PORT` | Port of the `/metrics` server in workers and relays (default 9100, `0` disables it) |
| `LOG_LEVEL` | Log level (default `INFO`) |

### Business and messaging metrics

| Series | Type | Emitted by |
|---|---|---|
| `http_requests_total`, `http_request_duration_seconds` | counter, histogram | every API |
| `marketplace_handler_duration_seconds{consumer_group,event_type,result}` | histogram | `KafkaEventConsumer` |
| `marketplace_dlq_messages_total{source_topic,consumer_group}` | counter | `KafkaEventConsumer` |
| `marketplace_outbox_published_total{topic,event_type}` | counter | `OutboxRelay` |
| `marketplace_outbox_pending` | gauge | `OutboxRelay` |
| `marketplace_outbox_relay_errors_total` | counter | `OutboxRelay` |
| `marketplace_orders_created_total` | counter | ordering (API) |
| `marketplace_payments_confirmed_total` | counter | payments (API) |

### Why propagate context through Kafka

In an HTTP call the context travels on its own, in the header, and the httpx and FastAPI instrumentation
takes care of it. Kafka is asynchronous: the publisher does not wait, and the consumer runs in another process,
sometimes minutes later. Without propagation, each consumer would open a new trace and an order would show up
as five disconnected stories, with no way to tell which payments event came from which order.

The solution has two halves:

1. The publisher injects `traceparent` into the message headers.
2. The consumer extracts the `traceparent` and creates the handler span as a child of it (`SpanKind.CONSUMER`).

There is a pitfall specific to anyone using an **outbox**: what publishes to Kafka is not the request, it is
the relay, in another process and at another time. If the relay injected its own context, the trace would be
born in the relay and the original request would be left out. That is why the context is **stored in the
outbox row** (the `outbox_events.traceparent` column) at the moment the event is written, inside the request or
handler span. The relay reads the value, opens a `<topic> publish` span as its child, and that is the span the
publisher injects into the headers.

```
POST /orders ──► outbox.add (stores traceparent) ──► [outbox_events]
                                                         │ relay reads the traceparent
                                                         ▼
                              span "orders.events publish" (child of POST /orders)
                                                         │ Kafka headers: traceparent
                                                         ▼
          span "orders.events process" (payments) ──► outbox.add ──► ... and so on
```

The result is a single trace covering the whole order. The library's tests prove this end to end with a real
Kafka: they publish inside a span, consume, and check that the `trace_id` is the same and that the parent
tree is correct.

## 2. DLQ (dead letter queue)

When a message handler fails, the consumer retries (up to `max_attempts`, with `error_backoff` between
attempts). Past the limit, the message goes to the `<source>.dlq` topic with three diagnostic headers and
consumption moves on. Without this, a "poison message" would block the whole partition and nothing after it
would be processed.

| Header | Content |
|---|---|
| `dlq_reason` | `repr` of the exception (up to 500 characters) |
| `dlq_source` | source `topic/partition/offset` |
| `dlq_group` | the consumer group that gave up |

The DLQ is a queue of **pending work**, not a dumping ground. Every message there is an event the business
needed to process and could not. The question is always "why did it fail?":

- **Transient failure or an already-fixed bug** (database down, bad deploy, flaky dependency): replaying
  fixes it. This is the common case.
- **Truly invalid message** (corrupted payload, a business rule that will never accept it): replaying just
  hands the problem back. Fix the data at the source or discard it as a conscious decision.
- **Replay only after fixing the cause.** Resending with the bug still active recreates the DLQ.

Replaying is safe because the consumers deduplicate by `event_id` (inbox): redelivering an event that was
already handled has no side effect.

### Tool

```bash
# summary: source, event type, reason, and count
uv run python -m marketplace_common.dlq list --topic orders.events.dlq

# dry run (default): shows what would be resent and sends nothing
uv run python -m marketplace_common.dlq replay --topic orders.events.dlq --event-type OrderCreated --limit 10

# actually executes
uv run python -m marketplace_common.dlq replay --topic orders.events.dlq --event-type OrderCreated --limit 10 --yes
```

The Kafka address comes from `--bootstrap` or from `KAFKA_BOOTSTRAP_SERVERS` (default `localhost:9094`).

Safety rules of `replay`:

- `--dry-run` is the default behavior. Only `--yes` publishes.
- The destination topic is read from each message's `dlq_source` header, and the original key is kept (the
  message goes back to the same partition, preserving per-order ordering).
- The `dlq_reason`, `dlq_source`, and `dlq_group` headers are removed and `dlq_replayed` (when) and
  `dlq_replayed_from` (from which DLQ position) are added.
- **Anti-loop:** after resending, the tool writes a marker into the DLQ itself. A message that was already
  replayed, or that came back to the DLQ carrying the `dlq_replayed` header, is refused unless `--force` is
  passed. This way a persistent bug does not turn into an infinite resend cycle.

### Retention (TTL) for outbox, inbox, and idempotency

Without cleanup, `outbox_events`, `inbox_messages`, and `idempotency_keys` grow forever. The `CleanupJob`
deletes whatever is past retention, in batches:

```sql
WITH doomed AS (
  SELECT ctid FROM outbox_events
  WHERE published_at < now() - make_interval(secs => :retention)
  ORDER BY published_at LIMIT :batch
  FOR UPDATE SKIP LOCKED)
DELETE FROM outbox_events WHERE ctid = ANY (ARRAY(SELECT ctid FROM doomed))
```

Each batch is a short transaction (1000 rows by default) and `SKIP LOCKED` skips whatever another transaction
holds, so nothing waits and several replicas of the job can run together. A cycle runs at most
`CLEANUP_MAX_BATCHES` batches, with a pause between them, and the next cycle picks up where it left off. The
**unpublished** outbox is never deleted (a null `published_at` column is not part of the comparison). Partial
indexes on `published_at`, `processed_at`, and `created_at` keep the lookup cheap.

| Variable | Default | Effect |
|---|---|---|
| `RETENTION_OUTBOX_PUBLISHED_HOURS` | 168 (7 days) | how long to keep the already-published outbox |
| `RETENTION_INBOX_HOURS` | 336 (14 days) | how long to keep the inbox dedup record |
| `RETENTION_IDEMPOTENCY_HOURS` | 48 | validity of the `Idempotency-Key` |
| `CLEANUP_INTERVAL_SECONDS` | 300 | interval between cycles |
| `CLEANUP_BATCH_SIZE` | 1000 | rows per batch |
| `CLEANUP_MAX_BATCHES` | 50 | batches per cycle and per table |
| `CLEANUP_PAUSE_SECONDS` | 0.05 | pause between batches |

Two safety rules of the policy: the inbox must last **longer** than the Kafka topic retention (deleting the
dedup record while the message can still come back reopens the door to processing twice), and the idempotency
key must outlast a client's longest retry window (after it expires, the same key creates a new order, and
there is a test for this).

Metrics: `marketplace_cleanup_deleted_total{table}`, `marketplace_cleanup_batches_total{table}`,
`marketplace_cleanup_runs_total{result}`, `marketplace_cleanup_run_duration_seconds`, and
`marketplace_cleanup_last_success_timestamp_seconds` (alert if it gets stale). The job runs inside the
`worker_main` of ordering, payments, inventory, ledger, and notifications, and in the identity API (expired
refresh tokens).

## 3. Shared library in microservices: coupling versus duplication

Sharing code between independent services is a trade-off, and it needs to be a conscious one.

| | Copy into each service | Shared library |
|---|---|---|
| Deploy autonomy | Total | A change in the lib requires updating every service that uses it |
| Bug fixing | Fix it N times (and forget one) | Fix it once |
| Consistency | The copies drift apart over time | A single behavior |
| Coupling | None between services | The lib version becomes an implicit contract |
| Risk | Different failures in each copy | One failure in the lib takes everyone down at once |

The practical rule used here: share **cross-cutting, stable infrastructure** (how to talk to Kafka, how to
emit logs and metrics, how to replay the DLQ) and **never business rules or domain models**. Each service
keeps its own use cases, its own entities, and its own tests. The lib knows nothing about `Order` or
`Payment`.

Precautions so the lib does not become a distributed monolith:

- A small, stable API, with optional extras so it does not impose dependencies.
- Compatible changes by default (the `traceparent` field of `OutboxMessage` is optional, with a default value).
- Tests in the lib itself, running once, instead of repeated across five services.
- In real production, publish the lib with semantic versioning to a package registry and pin the version in
  each service, so they can be upgraded one at a time. Here it is referenced by path because the repository is
  a study monorepo.

## 4. Bringing up the observability stack

```bash
cd infra
docker compose -f docker-compose.yml -f docker-compose.observability.yml --profile services up -d --build
```

| Tool | Address |
|---|---|
| Grafana ("Marketplace" dashboard) | http://localhost:3000 (admin / admin, anonymous read access enabled) |
| Jaeger (traces) | http://localhost:16686 |
| Prometheus | http://localhost:9090 |

The `docker-compose.observability.yml` file also injects `OTEL_EXPORTER_OTLP_ENDPOINT` into the services.
Without it the services work normally, just without traces.

## 5. Interview questions

**1. What is the difference between monitoring and observability?**
Monitoring checks known conditions ("did CPU go over 90%?") and tells you whether something is broken.
Observability is being able to investigate conditions nobody anticipated, from rich data (correlated logs,
metrics, and traces) emitted by the system itself. In microservices it matters more because a failure is
rarely in the service that shows it.

**2. What is each pillar for, and why all three together?**
Metrics tell you there is a problem and how big it is, cheaply and in aggregate. Traces show where, along the
path between services, the time was spent or the error originated. Logs give the detail of each execution.
The link between them is the `trace_id` in the logs and the same dimension in the labels: from the alert to
the trace, and from the trace to the log lines.

**3. What is the RED method, and when does it not fit?**
Rate, Errors, and Duration per service: the minimum to know whether something that serves requests is doing
well, from the caller's point of view. It does not fit resources (use USE: utilization, saturation, and
errors) or batch processes and consumers, where handler throughput, queue lag, and messages in the DLQ matter.

**4. Why use latency percentiles instead of the mean?**
The mean hides the tail. If 1% of requests take 5 s, the mean barely moves, but those users feel it. p95 and
p99 show the experience of the bad cases. That is why duration is a histogram, which lets you compute
percentiles in Prometheus with `histogram_quantile`.

**5. How does a trace cross Kafka if there is no HTTP request?**
The context goes in message headers (`traceparent`, W3C standard). The publisher injects it and the consumer
extracts it and creates the handler span as a child. With an outbox there is one extra step: the context is
stored in the outbox row at write time, because what publishes is the relay, in another process. Without
that, the trace would break at the relay.

**6. What is a DLQ, and when do you replay?**
It is the destination for messages that exhausted their retries, so they do not block the partition. You
replay after fixing the cause (a bug, a dependency that was down), in a controlled way: filtering by type,
with a limit, in dry run first, and with protection against looping resends. A truly invalid message is not
replayed; it is fixed or discarded. Consumer idempotency (inbox by `event_id`) is what makes this safe.

**7. Why does the consumer commit the offset only after handling the message?**
It is "at least once" delivery: if the process dies between handling and committing, the message is
redelivered. The handler is idempotent (inbox), so reprocessing is harmless. Committing first would flip the
risk to "at most once", with silent loss of events.

**8. Shared library or duplicated code across microservices?**
It depends on what is being shared. Stable cross-cutting infrastructure (messaging, observability) is worth a
lib: a bug fixed once and uniform behavior. Business rules and domain models are not, because they couple the
teams and the deploys. To keep the lib from becoming a distributed monolith: a small API, compatible changes,
semantic versioning, its own tests, and gradual upgrades, one service at a time.
