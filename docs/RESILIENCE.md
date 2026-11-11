**English** | [Português (Brasil)](pt-BR/RESILIENCIA.md)

# Resilience

This document explains the marketplace's resilience patterns: what each one solves, where it is applied,
how to configure it, the trade-offs, and how to defend each decision in an interview. They all live in the
shared library `backend/libs/marketplace_common/src/marketplace_common/resilience/` and are used by the
gateway, by `payments` (PSP client), by `assistant` (LLM and embedder), and by `ordering` (catalog call).

## 1. Overview

Failures in distributed systems are normal. The goal is not to avoid them, but to make sure a slow or dead
dependency does not take down the callers that depend on it. The order in which the patterns compose matters:

```
Retry  >  Circuit breaker  >  Bulkhead  >  Timeout (capped by the deadline)  >  call
```

- **Retry** is the outermost layer: every attempt goes through the breaker, so attempts against an open
  circuit are rejected immediately and **never** retried.
- The **breaker** wraps the bulkhead: a bulkhead rejection (the system is saturated) does not count as a
  dependency failure.
- The **timeout** is the innermost layer and is the smaller of the configured timeout and what is left of the
  deadline.

Where each pattern is applied:

| Call | Breaker | Retry | Bulkhead | Deadline | Rate limit |
|---|---|---|---|---|---|
| Gateway to each service (7 breakers) | yes, per service | GET and HEAD only | yes, per service | sets, forwards, and caps the timeout | yes, per client and per route |
| `payments` to the PSP (charge, status, cancel) | yes | yes (all 3 operations are idempotent) | yes | caps the timeout | no |
| `payments`, webhook: status lookup at the PSP | the same `ResilientPsp` | yes | yes | caps the timeout | no |
| `assistant` to the LLM and the embedder | yes, one per model | yes (reads), no on the stream | yes | caps the timeout | via gateway |
| `ordering` to the catalog | already had its own retry | already had it | no | forwards the header and caps the timeout | via gateway |
| Gateway to Redis (limiter) | yes | no | no | no | n/a |

## 2. Circuit breaker

**Problem.** A slow or dead service holds connections, threads, and memory on its callers, and the failure
cascades upward. Hammering it only makes recovery harder for the struggling service.

**How it works here** (`circuit_breaker.py`):

- Three states: `closed` (everything passes), `open` (rejects without calling the dependency), and `half_open`
  (lets a few probes through).
- Sliding window by count (`window_size`) **and** by age (`window_seconds`). It only evaluates after
  `minimum_calls` calls, so it does not trip on 1 failure out of 1 call.
- It opens on **failure rate** (`failure_rate_threshold`, default 50%) or on **slow-call rate**
  (`slow_call_threshold` and `slow_call_rate_threshold`). A dependency that answers 200 after 8 seconds also
  takes the system down, which is why slow calls count.
- In `half_open` it admits at most `half_open_max_calls` probes (concurrent and in total). A single failure
  reopens the circuit and restarts the wait. If all probes succeed, the circuit closes.
- `is_failure` decides what counts as a failure: 404s and validation errors do not count (the dependency is
  healthy), 5xx and transport errors do. `failure_on_result` flags bad responses that do not raise an exception.
- Cancellation and abandoned generators are neutral: they count as neither success nor failure and release the
  probe slot.
- Usable as a decorator (`@breaker.protect`), as a context manager (`async with breaker.guard()`), or as
  `await breaker.call(operation)`.

**Prometheus metrics:** `resilience_circuit_breaker_state{name,state}`,
`resilience_circuit_breaker_transitions_total{name,from_state,to_state}`,
`resilience_circuit_breaker_calls_total{name,outcome}`, `resilience_circuit_breaker_rejected_total{name}`.

**When to use it.** On every network call to a dependency that can degrade.
**When not to use it.** On local calls or inside a database transaction, where "opening" helps no one.

**Trade-offs.** A short window reacts fast but flaps. A long window is stable but takes longer to protect.
A low `minimum_calls` trips on noise. State is per process: each gateway replica learns on its own (cheap and
no central point, but replicas diverge for a few seconds).

**Per-process state and the shared mode (optional).** By default each gateway instance has its own breaker:
a replica that has not seen failures yet keeps sending traffic to a service another replica already considers
unhealthy, and each replica spends its own calls to find out. With `BREAKER_SHARED_STATE=true` (requires
`REDIS_URL`, off by default) the gateway uses `SharedCircuitBreaker` (`resilience/shared_breaker.py`): the
replica that opens the circuit writes a `gw:cb:<service>` key to Redis that lives for `open_seconds`; the other
replicas read the key (at most every `BREAKER_SYNC_INTERVAL`, 0.25 s) and open too, with the remaining time;
the replica that closes the circuit deletes the key. What stays local: the failure window and the half-open
probe count (each replica probes on its own). If Redis fails, the breaker falls back to the local one and the
call is unaffected. Tests: `tests/unit/test_shared_breaker.py` (two replicas converge, the remaining window
matches, recovery, Redis failure), `tests/integration/test_redis_shared_breaker.py` (real Redis), and
`gateway/tests/test_shared_breaker.py` (two gateway instances: the one that has not seen a failure answers
`503 circuit_open` without calling the service).

**.NET equivalent.** Polly `AdvancedCircuitBreaker` (v7) or `AddCircuitBreaker` in
`Microsoft.Extensions.Resilience` (Polly v8): `FailureRatio` = `failure_rate_threshold`,
`SamplingDuration` = `window_seconds`, `MinimumThroughput` = `minimum_calls`, `BreakDuration` =
`open_seconds`. The slow-call rate matches Resilience4j's `SlowCallDurationThreshold`.

**In an interview.** "I use a breaker with a sliding window, failure rate and slow-call rate, and limited
probes in half-open. Each dependency has its own, so a catalog outage does not affect inventory. When it
opens, the gateway returns a structured 503 with Retry-After in 10 ms instead of holding the connection for
10 seconds."

## 3. Retry with exponential backoff, full jitter, and a budget

**Problem.** Transient failures (a reset connection, a 503 during a deploy) disappear if the call is repeated.
But badly done retry is the main cause of retry storms: if 3 layers make 3 attempts each, 1 request becomes
27 against a service that is already going down.

**How it works here** (`retry.py`):

- Delay = `uniform(0, min(max_delay, base * 2^(attempt-1)))`: exponential backoff with **full jitter**.
  Jitter spreads clients out in time; without it, they all retry at the same instant and create synchronized spikes.
- It only retries if `idempotent=True` **and** the error is transient (`retry_on`) **or** the result is bad
  (`retry_on_result`, e.g. 502, 503, 504). At the gateway, only `GET` and `HEAD` are retried. `POST /orders`
  is never repeated by the gateway: the client repeats it, with the same `Idempotency-Key`.
- It never retries `CircuitOpenError`, `BulkheadFullError`, or `DeadlineExceeded`.
- It does not sleep past the deadline: if the delay does not fit in the remaining time, it gives up immediately.
- **Retry budget** (`RetryBudget`): in a 10 s window, the allowed retries are
  `min_retries + ratio * requests` (default 3 + 20%). With the service down, the budget runs out and the system
  stops amplifying load. The metric `resilience_retry_events_total{event="budget_denied"}` shows this.

**When to use it.** Reads and idempotent operations.
**When not to use it.** On writes without an idempotency key (charging twice is worse than failing once) and on
deterministic errors (400, 404, 422), which fail the same way every time.

**Trade-offs.** More attempts raise the odds of success and also tail latency. The budget trades a bit of
availability for protection against the thundering herd. Retry across multiple layers multiplies, which is why
the gateway is the only place that retries HTTP read calls.

**.NET equivalent.** Polly v8 `RetryStrategyOptions` with `BackoffType = Exponential`, `UseJitter = true`,
`MaxRetryAttempts`, `ShouldHandle` (= `retry_on` and `retry_on_result`). The budget does not exist in Polly: it
is a concept from Finagle and Envoy (`retry_budget`), and here it is hand-rolled.

**In an interview.** "Exponential backoff with full jitter, only on idempotent operations, respecting the
deadline and with a retry budget expressed as a fraction of traffic. Without a budget, retry becomes an attack
on your own service."

## 4. Deadline propagation (cascading timeouts)

**Problem.** If the gateway waits 10 s and the service below it waits another 10 s on the next one, the client
has already given up and the work keeps going for nothing. Independent timeouts at each hop add up instead of
bounding each other.

**How it works here** (`deadline.py`):

- The gateway creates a per-request time budget: the client's `X-Request-Deadline` (capped at
  `max_request_deadline_seconds`, 30 s) or the default `request_deadline_seconds` (8 s; 25 s for
  `assistant`, which can take longer).
- The header carries the **remaining time in milliseconds**, not an absolute timestamp (`grpc-timeout` style).
  That way it does not depend on synchronized clocks: each hop converts it to its own monotonic clock.
- Every outbound call recomputes what is left, writes it to the header, and **caps the httpx timeout** at what
  remains (`deadline_event_hooks`). A gateway, ordering, and catalog chain never exceeds the original budget.
- Every API that uses `install_api_observability` installs the `DeadlineMiddleware`: it reads the header,
  answers `504` if the request arrives already expired (no work is spent), and exposes the budget through
  `current_deadline()`.
- Retry checks the deadline before sleeping; `ResilientPsp` and `ModelGuard` cap `asyncio.timeout`.

**Trade-offs.** The deadline is cooperative: the middleware does not cancel handlers in the middle of a
transaction (cancelling mid-commit is worse than finishing). That is why it is the outbound calls that honor
the budget.

**.NET equivalent.** A `CancellationToken` propagated end to end, plus `HttpClient.Timeout` and Polly's
`TimeoutStrategy`. In gRPC it is the native *deadline*.

**In an interview.** "A per-hop timeout is not enough. I propagate the remaining time as a relative header and
each layer caps its calls to it. When the budget runs out, it fails fast with a 504 instead of working for a
client that already left."

## 5. Bulkhead

**Problem.** A slow dependency eats all the shared connections and threads, and the other (healthy) routes run
out of resources too. It is the principle of a ship's watertight compartments.

**How it works here** (`bulkhead.py`): one semaphore per dependency with `max_concurrent` simultaneous
executions and a short queue of `max_queue` waiters, each waiting up to `queue_timeout`. Beyond that, it
rejects immediately (`BulkheadFullError`, a 503 with `Retry-After` at the gateway). Metrics:
`resilience_bulkhead_in_flight`, `resilience_bulkhead_queued`, `resilience_bulkhead_rejected_total{reason}`,
and the wait-time histogram.

**Trade-offs.** A low limit protects but turns away legitimate traffic during a spike. A long queue hides
saturation and increases latency (and by then the client has already given up). Prefer a short queue and fail
fast.

**.NET equivalent.** Polly v7's `BulkheadPolicy`. In v8 it became the `ConcurrencyLimiter`
(`AddConcurrencyLimiter`), with `PermitLimit` and `QueueLimit`.

**In an interview.** "Each dependency has its own concurrency limit and a small queue. An assistant outage does
not consume the catalog's connections."

## 6. Distributed rate limiter on Redis

**Problem.** Protect the system from an abusive client or a runaway loop. An in-memory limiter only knows the
traffic of its own replica: with 5 replicas, the real limit is 5 times higher.

**How it works here** (`rate_limit.py`):

- **Token bucket** in a Lua script, executed atomically on Redis (a single `EVALSHA`, no race condition
  between replicas). The key is `gw:rl:<route>:<client>`; the state is a hash with `tokens` and `ts`, with
  `PEXPIRE` so an idle bucket disappears on its own. The clock is Redis's (`TIME`), so replicas with different
  clocks agree. In tests, time is injected.
- Limit per client (IP) **and** per route (service name). Default: 600 per minute, with `ordering` at 120 and
  `assistant` at 60, configurable through `RATE_LIMIT_PER_MINUTE` and `RATE_LIMIT_ROUTES` (JSON). A token
  bucket allows bursts up to capacity and refills continuously, which is friendlier than a fixed window (which
  lets double the traffic through at the window boundary).
- Responses carry `RateLimit-Limit`, `RateLimit-Remaining`, and `RateLimit-Reset` (seconds until full), and the
  `429` carries `Retry-After`.
- **If Redis goes down** (`RATE_LIMIT_FAILURE_MODE`): `fallback` (default) uses the per-instance in-memory token
  bucket, `fail_open` lets everything through, and `fail_closed` blocks. All of them are counted in
  `resilience_rate_limit_backend_total{backend}`. A dedicated circuit breaker avoids paying the Redis timeout
  on every request while it is down.

**Trade-offs.**

- Fail-open favors availability (and leaves you without abuse protection). Fail-closed favors protection (and a
  Redis outage takes the product down). The in-memory fallback is the middle ground: the limit stops being
  global, but it still exists.
- Redis enters the critical path of every request: it costs 1 round trip (about 1 ms on the same network), so
  it has a short timeout and a breaker.
- Client identity: the connection IP or, only when the connection comes from a proxy listed in
  `TRUSTED_PROXIES` (CIDR, comma-separated), the first untrusted address in `X-Forwarded-For`, read from right
  to left (`X-Real-IP` if it is missing). Without the list, the header is ignored: a client cannot forge its IP
  to dodge the limit (test: `test_a_client_cannot_dodge_the_limit_by_forging_forwarded_for`). The gateway
  forwards the resolved address to the services in `X-Forwarded-For`. In compose the default is the entire
  private range (the Docker network); in production, list only the load balancer's addresses.

**.NET equivalent.** `Microsoft.AspNetCore.RateLimiting` with `TokenBucketRateLimiter` (per policy and per
partition). The distributed version requires a package such as `RedisRateLimiting` or a Lua script like the one
here. Polly v8 has `AddRateLimiter`, but it is client-side.

**In an interview.** "Token bucket in Lua, atomic, using the Redis clock. Per client and per route. If Redis
goes down, the behavior is a product decision, and it is configurable: I fall back to local memory, let traffic
through, or block. In every case there is a metric and an alert."

## 7. Graceful degradation

The gateway's error contract (`{ "detail": "text" }`) still holds, with optional extra fields:

| Situation | Status | Body and headers |
|---|---|---|
| A service's circuit is open | 503 | `{"detail": "catalog is temporarily unavailable", "code": "circuit_open", "service": "catalog", "retry_after_seconds": N}` and `Retry-After: N` |
| Bulkhead full | 503 | same shape, `code: "overloaded"` |
| Request limit | 429 | `Retry-After` and `RateLimit-*` |
| Deadline exceeded | 504 | `{"detail": "request deadline exceeded"}` |
| Upstream timeout | 504 | `{"detail": "upstream timeout"}` |
| Upstream down (no breaker open yet) | 502 | `{"detail": "upstream unavailable"}` |
| PSP unavailable on the webhook | 503 | `{"code": "psp_unavailable"}` and `Retry-After` (the PSP resends the webhook) |
| LLM or embedder guarded and open | 503 | `{"code": "model_unavailable"}` and `Retry-After` |

`GET /api/health` aggregates each service's `/health` and now includes `breakers` (state, failure rate, and
time until the next probe for each service). It reports `degraded` if any service is down **or** any breaker is
not closed.

Most important: **isolation is per service**. With the catalog down, inventory, the ledger, and order reads keep
responding. And the money flow does not depend on a synchronous call: the order is written together with the
event in the outbox in the same transaction, so if `payments` is down the saga simply waits on Kafka and
continues when it comes back.

## 8. Observability and SLOs

- **Resilience** Grafana dashboard (`infra/observability/grafana/dashboards/resilience.json`): breaker state,
  transitions, rejections, retries, bulkhead, rate-limit decisions, which backend answered the limit (Redis or
  fallback), 429s, 503s, and 504s at the gateway, deadlines exceeded, and the SLO section.
- Prometheus rules in `infra/observability/rules/resilience-slo.yml` (validated with `promtool check rules`
  and tested with `promtool test rules` in `infra/observability/tests/`).
- **Gateway SLOs:** 99.5% availability (responses that are not 5xx) and latency with 95% of responses under
  500 ms.
- **Burn-rate alerts**, over two windows, as in Google's SRE book. The *burn rate* is how fast the error budget
  is being consumed: 1 spends the budget exactly at the end of the month.

| Alert | Windows | Burn rate | Severity |
|---|---|---|---|
| `...BurnRateFast` | 1h and 5m | 14.4 (runs out in about 2 days) | page |
| `...BurnRateSlow` | 6h and 30m | 6 | page |
| `...BurnRateTicket` | 1d and 2h | 3 | ticket |

Pairing the short window with the long one avoids alerting on a spike that has already passed and makes the
alert clear quickly. There are also alerts for an open breaker, a flapping breaker, a rate limiter without Redis
(and in fail-closed), excess 429s, bulkhead rejections, an exhausted retry budget, and deadline spikes.

## 9. How it was tested

- **Unit tests** (injectable clock, no real `sleep`): breaker, retry, deadline, bulkhead, and rate limiter in
  the lib, plus gateway, `payments`, `assistant`, and `ordering`.
- **Integration with real Redis:** the Lua script (burst, refill, TTL, atomicity with 200 concurrent calls, two
  limiters sharing the same bucket, server clock) and two gateway instances sharing the same limit.
- **Chaos** (`scripts/chaos.sh`): takes down catalog, payments, and Redis one at a time, on the real stack.
  It validates that the breaker opens, that the response is fast (503 in a few milliseconds), that the system
  recovers on its own, and that orders created before and during the payments outage reach `PAID`. Results in
  section 10.
- **Load** (`scripts/loadtest.py`): see `docs/LOAD-TEST.md`.
- **Alerts:** `promtool test rules` simulates error series and confirms the alerts fire (and do not fire on
  healthy traffic).

## 10. Measured results

See `docs/LOAD-TEST.md` (load) and the output of `scripts/chaos.sh`, summarized below.

Last run of `scripts/chaos.sh` against a parallel Docker stack (40 checks, 40 passed):

| Scenario | Measured result |
|---|---|
| Catalog taken down | the breaker opened after 25 calls; with the circuit open, the gateway answered `503` with `Retry-After` in a few milliseconds; inventory kept responding; `POST /orders` degraded with a 503 |
| Catalog comes back | it answered 200 again on its own, without restarting the gateway, and the breaker closed after the half-open probes |
| Payments taken down | one order created before and another during the outage; a payment lookup with the circuit open answered 503 fast; ordering kept serving order reads |
| Payments comes back | the charges for both orders were created about 8 s later (the saga resumed from Kafka) and both reached `PAID` |
| Redis taken down | 30 of 30 requests answered 200, with p50 of 12 ms, p90 of 18 ms, and a max of 28 ms; the `memory_fallback` metric went up and the `RateLimit-*` headers kept coming out |
| Redis comes back | the gateway went back to using Redis on its own |

In the first version of the script, the max without Redis reached 2 to 3 seconds: redis-py's cleanup of the
cancelled connection was holding up the response. The limiter now awaits the operation in a separate task and
answers at the timeout without waiting for that cleanup (test
`test_slow_cancellation_cleanup_does_not_delay_the_answer`). The measured max dropped to under 600 ms in
manual repeat runs, and p90 stayed below 250 ms.

## 11. Lessons learned and pitfalls

- **An abandoned generator is not a failure.** On the LLM stream, a client that closes the connection ends the
  generator with `GeneratorExit`. If the breaker treated that as an error, opening a tab and closing it would
  trip the circuit. Now cancellation and `GeneratorExit` are neutral.
- **The Redis timeout also measures event-loop latency.** With the gateway at 100% CPU, a 100 ms Redis timeout
  fired because of the loop's own delay, and the Redis breaker flapped 5 times in one load run. The default
  went up to 250 ms and the breaker now requires more samples (10 calls, window of 30). The in-memory fallback
  held the traffic the whole time, and that is what the dashboard showed.
- **A new dependency in a shared lib breaks the services that do not use it.** The `httpx` used by the
  deadline was not in the lib's dependencies and took down, only inside Docker, the services that did not
  declare it. Fixed by declaring the dependency. Lesson: test the image, not just the dev environment.
- **Half-open needs traffic to close.** After the dependency comes back, the breaker only closes after the
  successful probes. The chaos script sends requests until the breaker closes instead of assuming it closes
  on its own at that instant.
- **A load test consumes stock.** Each order reserves units; `loadtest.py` restocks before starting, otherwise
  orders start getting cancelled for lack of stock and mask the result.

## 12. Interview questions and short answers

**What is the difference between timeout, retry, and circuit breaker?**
Timeout limits how long to wait for a call. Retry tries again when the failure looks transient. The breaker
stops calling something that is unhealthy. Combined, retry sits outside the breaker and the timeout inside.

**Why jitter?** Without it, all clients retry at the same instant and create synchronized spikes. With full
jitter, the delay is drawn between 0 and the exponential ceiling, which spreads the load.

**How do you avoid a retry storm?** Mandatory idempotency, a budget expressed as a fraction of traffic, retry
at a single layer, and never against an open circuit.

**Is retrying a POST safe?** Only with an idempotency key. Here the gateway does not retry POST: the client
resends with the same `Idempotency-Key` and `ordering` returns the same result.

**What happens if the rate limit's Redis goes down?** It depends on the policy: fall back to memory (default),
let traffic through, or block. The Redis breaker avoids waiting for a timeout on every call, and there is a
metric and an alert.

**Why token bucket and not a fixed window?** It accepts a controlled burst, refills continuously, and does not
have the double-traffic problem at the window boundary.

**How do you guarantee an order is not lost if payments goes down?** The order and the outbox event are written
in the same transaction. The event waits on Kafka, and when payments comes back the consumer (with an inbox,
which deduplicates) creates the charge. The chaos test proves it.

**Per-process or shared breaker?** Per process: simple, no central point, no network cost. The price is that
replicas learn independently. Sharing state in Redis only pays off if the decision needs to be identical across
all replicas. The gateway supports both: per process by default, and an optional shared mode
(`BREAKER_SHARED_STATE=true`) where only the decision to open is shared through Redis.

**How do you choose thresholds?** I start conservative (50% failure rate, minimum of 10 calls), watch the
dashboard under real load, and adjust. Measure before configuring: the Redis timeout case shows why.

**Polly equivalents:** see the table below.

| Here | Polly v8 / ASP.NET Core |
|---|---|
| `CircuitBreaker` | `AddCircuitBreaker` (`FailureRatio`, `SamplingDuration`, `MinimumThroughput`, `BreakDuration`) |
| `retry_async` + `RetryPolicy` | `AddRetry` (`BackoffType.Exponential`, `UseJitter`, `MaxRetryAttempts`, `ShouldHandle`) |
| `RetryBudget` | no native equivalent (Finagle and Envoy `retry_budget`) |
| `Deadline` | propagated `CancellationToken`, `AddTimeout`, gRPC deadline |
| `Bulkhead` | `AddConcurrencyLimiter` (was `BulkheadPolicy` in v7) |
| `RouteRateLimiter` | `Microsoft.AspNetCore.RateLimiting` (`TokenBucketRateLimiter`), distributed version with Redis |
| structured 503, in-memory fallback | `AddFallback` |
| `retry > breaker > bulkhead > timeout` composition | order of the `AddX` calls in `ResiliencePipelineBuilder` |

## 13. Known limitations

- Breaker state is per process unless `BREAKER_SHARED_STATE=true` (section 2): in shared mode, only the
  decision to open is global; the failure window and the probes stay local.
- With `TRUSTED_PROXIES` set to the private range (the compose default), anyone who reaches the gateway
  directly through the port published on the host (which arrives via the Docker bridge gateway, also private)
  can forge `X-Forwarded-For` in development. In production, use the proxy's exact addresses.
- The deadline is cooperative: handlers already inside a transaction are not cancelled.
- The breaker counts 5xx responses as failures, including a 500 caused by a service bug, which is what you want
  to protect the caller, but it can open the circuit over a code error.
- The assistant's SSE stream holds a bulkhead slot only until the headers arrive. The stream body does not
  occupy a slot.
- Prometheus retention in compose is 3 days: the 1-day ticket alert works, but there is no history for a 30-day
  SLO window.
