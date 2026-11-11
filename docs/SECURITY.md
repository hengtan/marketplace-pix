**English** | [Português (Brasil)](pt-BR/SEGURANCA.md)

# Security

A condensed threat model (STRIDE), a map of the OWASP API Security Top 10 (2023) to what was built, known
limitations, and an interview talking script. The identity architecture decision is in
`docs/adr/0001-identity-as-a-service.md`, and the route contracts are in `docs/CONTRACTS.md`.

## 1. Trust boundaries

```
Internet ──► gateway ──► services (ordering, ledger, inventory, ...) ──► Postgres, Kafka
             │   ▲
             │   └── JWKS (public key) ◄── identity (keys, passwords, refresh tokens)
             └── strips X-User-*, validates the JWT, signs the identity it forwards
```

| Boundary | Who crosses | Control |
|---|---|---|
| Internet → gateway | any client | rate limit, per-origin CORS, per-route policy, validated JWT |
| gateway → service | only the gateway (but the ports are published on the host) | HMAC-signed identity, bound to the `X-Request-Id` and a 60 s timestamp |
| service → service | `ordering` → `catalog`, `assistant` → others | `assistant` looks up the order with the chat user's signed identity (guests go anonymous); the others call as anonymous and only reach what is public |
| service → Kafka → service | events | versioned events, deduplicated by inbox, with contract golden files |
| PSP → payments | webhook | HMAC on the body and a re-query to the PSP before confirming |

Secrets come in **only through environment variables** (`INTERNAL_AUTH_SECRET`, `IDENTITY_SIGNING_KEY`,
`IDENTITY_SEED_PASSWORD`, `PSP_WEBHOOK_SECRET`, database passwords). Nothing is committed. In development,
`scripts/up.sh` generates the values into `.env` (ignored by git) and `identity` generates an ephemeral signing
key at startup. Outside development, `ENVIRONMENT=production` requires the key and the secret, and the gateway
refuses to start without `INTERNAL_AUTH_SECRET`.

## 2. STRIDE

| Threat | Where | Example | Mitigation | Evidence (test) |
|---|---|---|---|---|
| **S**poofing | Gateway, headers | client sends `X-User-Id: <admin>` | the gateway strips every client-supplied `X-User-*`, `X-Auth-*`, and `Authorization` and injects the signed identity; a service without a valid signature sees an anonymous caller | `test_client_supplied_identity_headers_never_reach_upstreams`, `test_forged_and_replayed_identity_is_ignored` (ledger), `test_a_forged_identity_header_is_not_trusted` (ordering) |
| Spoofing | Tokens | `alg: none`, HS256 with the public key, unknown `kid`, token from another issuer | algorithm pinned to `EdDSA`, `iss`, `aud`, `exp`, and `iat` required, JWKS with throttled reloads | `test_invalid_tokens_are_rejected_with_401` (10 variations) |
| Spoofing | Login | enumerating emails by timing or by message | same response and same hashing work for unknown email, wrong password, and locked account | `test_unknown_user_costs_the_same_hash_work`, `test_login_failures_do_not_reveal_whether_the_email_exists` |
| **T**ampering | Internal identity | changing the role on the gateway → service hop | HMAC over user, roles, scopes, merchant, timestamp, and request id | `test_tampered_roles_are_rejected`, `test_signature_is_bound_to_the_request` |
| Tampering | Order | client sends a price or `merchant_id` | price and merchant come from the catalog; the body ignores anything it does not declare | `test_price_sent_by_the_client_is_ignored` |
| Tampering | Events | a producer changes the format without notice | golden files and `schema_version` | `test_a_producer_that_adds_a_field_without_a_new_version_breaks_the_contract` |
| Tampering | PSP webhook | confirming a forged payment | HMAC on the body and a re-query to the PSP (fail-closed) | e2e: a webhook without a signature returns 401 |
| **R**epudiation | Late payment, timeout | "the order was cancelled and nobody knows why" | `order_audit` table (timeout, late payment) with a unique key, events in the outbox, metrics, and `request_id` in the logs | `test_payment_after_the_timeout_is_refunded_not_applied` |
| Repudiation | Sessions | a user denies a login | refresh tokens per family with usage and revocation timestamps; reuse is logged with user and family | `test_reusing_a_rotated_token_revokes_the_whole_family` |
| **I**nformation disclosure | Orders | user B reads user A's order | per-object authorization in the service; someone else's order answers `404`, identical to a nonexistent one | `test_bola_user_b_cannot_read_user_a_order`, `test_a_nonexistent_order_looks_the_same_as_someone_elses` |
| Information disclosure | Multi-tenant | merchant A reads B's ledger or stock | `merchant_id` comes from the token, never from the client; ledger, stock, and the order queue check the owner | `test_merchants_are_isolated_in_the_summary`, `test_merchant_updates_only_their_own_products`, `test_merchant_sees_only_orders_and_items_of_their_own_store` |
| Information disclosure | Credentials | database leak | passwords in argon2id, refresh tokens stored only as SHA-256, JWKS without private material | `test_argon2id_hashes_verify_and_are_salted`, `test_jwks_never_exposes_private_material` |
| **D**enial of service | Gateway | flood of requests | per-IP limit (the real IP only comes from `X-Forwarded-For` of a proxy listed in `TRUSTED_PROXIES`), 1 MiB body limit (`413`), capped pagination, max `page_size`, capped items and quantity | `test_rate_limit_returns_429_with_retry_after`, `test_a_client_cannot_dodge_the_limit_by_forging_forwarded_for`, `test_a_body_over_the_limit_is_refused_before_reaching_the_upstream` |
| Denial of service | Signup and login | mass signup, password guessing across many IPs or emails | distributed limit per IP+email and per IP on Redis, progressive wait after consecutive failures (2 s, 4 s, ... 15 min), account lockout | `test_mass_signup_from_one_ip_is_stopped`, `test_failed_logins_back_off_progressively_and_success_resets`, `test_two_identity_instances_share_the_limit_and_the_backoff` |
| Denial of service | Login | a huge password to burn argon2 CPU | password up to 128 characters; hashing outside the event loop; per-account lockout | `test_weak_passwords_are_rejected` |
| Denial of service | JWKS | flooding the gateway with fake `kid`s to force calls to identity | at most one reload every 10 s | `test_jwks_refresh_is_throttled_against_unknown_kid_floods` |
| Denial of service | Database | support tables growing without bound | batched retention with `SKIP LOCKED` | `test_writers_are_not_blocked_while_a_big_cleanup_runs` |
| **E**levation of privilege | Registration | `roles: ["admin"]` on signup | signup only creates `customer`; merchant and admin only through `POST /auth/admin/users` | `test_register_ignores_a_client_supplied_role` |
| Elevation of privilege | Routes | a customer calling a merchant route | policy by method, path, and scope at the gateway, reapplied in the service | `test_role_based_authorization` (15 cases), `test_every_endpoint_requires_authentication` |
| Elevation of privilege | Refresh | refresh token theft | rotation and reuse detection revoke the family **and its access tokens** (a list of `jti`s on Redis); absolute lifetime of 30 days | `test_concurrent_refresh_with_one_token_has_a_single_winner`, `test_reuse_detection_revokes_the_access_tokens_of_the_family` |
| Information disclosure | Assistant (RAG) | asking for someone else's order through the chat | the chat queries ordering with the user's signed identity: an account order only goes to its owner (IDOR), a guest order by id | `test_another_user_cannot_read_the_order_through_the_chat`, `test_unsigned_or_forged_identity_headers_are_treated_as_anonymous` |
| Information disclosure | Public stock | a competitor gauging demand through `reserved` | the public read returns only `available`; `reserved` only to the owning merchant and the admin | `test_anonymous_readers_only_get_available`, `test_the_owner_merchant_sees_reserved_of_its_own_products_only` |

## 3. OWASP API Security Top 10 (2023)

| # | Risk | What was done | Honest gap |
|---|---|---|---|
| API1 | Broken object level authorization (BOLA/IDOR) | An order belongs to the token's `owner_id`; `GET /orders/{id}` for someone else's order gives `404`; listing only returns the token's orders; payment only answers to whoever can see the order (the gateway queries ordering with the caller's identity); ledger and stock check the merchant; BOLA tests in memory, with real Postgres, and in the e2e (`scripts/e2e.sh`, section 6) | A **guest** order can be read by anyone who has the id (uuid v4, not guessable). `GET /notifications/{id}/preview` requires a token but does not check the owner |
| API2 | Broken authentication | argon2id, 10-minute `EdDSA` JWT with `kid`, `jti`, and JWKS, pinned algorithm, opaque rotating refresh with reuse detection, **access token revocation** on logout and on reuse (a list of `jti`s on Redis, 401 within 1 s), absolute session lifetime, per-account lockout (5 failures, 15 min), per-IP+email limit and progressive wait on `register` and `login`, identical responses and timing for an unknown email, `Cache-Control: no-store` on tokens | No MFA, no email verification, no breached-password check |
| API3 | Broken object property level authorization | Closed input schemas (signup does not accept roles, the order does not accept price or merchant); the merchant view is its own model, without the customer's email and with only their items | The schemas ignore extra fields instead of rejecting them |
| API4 | Unrestricted resource consumption | Distributed per-client limit at the gateway (Redis, with in-memory fallback), body limit (`413`), max `page_size`, up to 50 items and 99 units per order, password up to 128 characters, timeouts and `502/504` on upstreams, batched retention for the support tables | With Redis down the limit falls back to each instance's memory |
| API5 | Broken function level authorization (BFLA) | Route matrix by method and scope at the gateway (`gateway/auth/policy.py`), an unknown route requires a token, admin routes (`/auth/admin`, assistant reindex, reconciliation) only with the admin scope | The policy lives in the gateway code, not in an external declarative file |
| API6 | Unrestricted access to sensitive business flows | Idempotency on the order, stock reservation with a TTL and saga-timeout cancellation (no stock hoarding), late payment refunded, expired charge cancelled at the PSP, guest checkout can be turned off (`ALLOW_GUEST_CHECKOUT=false`), mass signup slowed by limits and progressive wait | No captcha or proof of work: an attacker with many IPs can still create accounts slowly |
| API7 | SSRF | The gateway only talks to the fixed list of upstreams in the configuration; no endpoint takes a URL from the client | The assistant has tools that call other services, but only with fixed URLs from the configuration |
| API8 | Security misconfiguration | Per-origin CORS, security headers on every gateway response (`X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Resource-Policy`; HSTS behind the `HSTS_ENABLED` flag, off in development), development routes off by default and authenticated when on, the gateway refuses to start without the internal secret, production requires a signing key, secrets only through the environment, errors without internal details | No CSP (the gateway only serves JSON; CSP belongs to the frontend server); service ports published on the host in development (which is why identity is signed) |
| API9 | Improper inventory management | A single table of routes and ports (`docs/CONTRACTS.md`), versioned events and golden files, a documented access matrix, development routes marked | No automatic discovery of exposed routes (a consolidated `openapi`) |
| API10 | Unsafe consumption of APIs | Price and merchant come from the catalog and not from the client, PSP webhook with HMAC and re-query, events validated by model and with retry and DLQ, event contract tested on both sides | The catalog and the simulated PSP are trusted by construction in this study project |

## 4. How authorization is built

1. **Gateway** (`backend/gateway/src/gateway/auth/`): `policy.py` says, by method and path, whether the route is
   public, optional, or required and which scope it demands. `verifier.py` validates the JWT. `guard.py`
   applies the policy, forces `customer_id` on notifications, queries ordering to protect payment, and signs
   the identity.
2. **Library** (`marketplace_common.security`): `Principal`, roles, scopes, and the HMAC signature. The one that
   verifies is the `PrincipalResolver` dependency, the same in every service.
3. **Services**: each one reapplies the object-level rule that only it knows (order owner, ledger merchant,
   product merchant). Without a signed identity, the call is anonymous.

Scopes are derived from the roles (`customer`, `merchant`, `admin`) when the token is issued. The merchant
carries `merchant_id` in the claim, and that is what becomes the tenant in every query.

## 5. Operations

| Topic | How |
|---|---|
| Signing key rotation | publish the new key in `IDENTITY_SIGNING_KEY` and the old public key in `IDENTITY_RETIRED_PUBLIC_KEYS`; the JWKS exposes both, and old tokens stay valid until they expire (10 min) |
| Generating a key | `python -m identity.keys_cli` prints an Ed25519 PEM on one line, ready for the environment variable |
| `INTERNAL_AUTH_SECRET` rotation | change it on all services and on the gateway; the signed identity lasts 60 s, so the incompatibility window is short |
| Revoking a user | `disabled = true` blocks login and refresh and, on the next refresh, puts live access tokens on the revoked list; without waiting, the token expires within 10 min |
| Access token revocation | on logout, on refresh reuse, and on a disabled account, identity writes `auth:revoked:<jti>` to Redis with a TTL equal to the token's remaining life (plus 10 s of slack). The gateway checks the list with a 0.5 s cache. With Redis down: `REVOCATION_FAIL_OPEN=true` (default) accepts the token, which still expires in 10 min; `false` answers `503` to anyone holding a token. Metric: `identity_access_token_revocations_total{result}` |
| Signup and login limits | `AUTH_LOGIN_PER_MINUTE_IP_EMAIL` (10), `AUTH_LOGIN_PER_MINUTE_IP` (60), `AUTH_REGISTER_PER_HOUR_IP_EMAIL` (5), `AUTH_REGISTER_PER_HOUR_IP` (30), `AUTH_BACKOFF_BASE_SECONDS` (2), `AUTH_BACKOFF_MAX_SECONDS` (900); metric `identity_abuse_blocks_total{action,reason}` |
| Investigating refresh token reuse | metric `identity_refresh_total{result="reuse"}` and the log `refresh token reuse detected` with user and family |
| Investigating a late payment | metric `marketplace_saga_late_payments_total`, the `order_audit` table, and the `PaymentRefundRequested` event |

## 6. Known limitations

- Access token revocation depends on Redis: with it down and `REVOCATION_FAIL_OPEN=true`, a revoked token becomes valid again until it expires (at most 10 minutes). Even with Redis up there is the gateway's 0.5 s cache window.
- The refresh token goes in the response body. A production frontend should keep it in an `HttpOnly` cookie
  behind a BFF, with the access token only in memory.
- The signup and login limit has no captcha: many distinct IPs can still create accounts slowly. `X-Forwarded-For` is only trusted from a proxy listed in `TRUSTED_PROXIES`; the compose default (private range) lets anyone who reaches the gateway port through the host forge the header in development.
- Stock `reserved` is gone from public responses; a frontend that still reads it must treat it as optional.
- Guest checkout relies on the order id as an access secret.
- Secrets in environment variables are the acceptable minimum; in production, a vault and automatic rotation are warranted.

## 7. Interview talking script

**"How did you handle security in this marketplace?"**

> I started with the threat model, in STRIDE, and closed the gaps in order of risk. The first problem was that
> nothing had an owner: anyone could read anyone's order and mess with stock. I created a separate identity
> service, because I want the edge proxy to hold only the public key, with no passwords and no private key. It
> uses argon2id, issues a short-lived JWT signed with EdDSA, and publishes the keys in a JWKS, and the refresh
> token is opaque, rotating, and has reuse detection: if someone presents a token that was already used, the
> entire session is revoked.
>
> The gateway validates the token, **strips** any identity header the client sent, and injects its own, signed
> with HMAC and bound to the request id. That matters because the service ports are also open in the local
> environment, so I cannot trust a header just because it "came from the gateway". Each service reapplies the
> object-level rule: the order belongs to its owner, the ledger and stock belong to the token's merchant. The
> `merchant_id` comes from the claim, never from a parameter, which is why isolation between merchants is
> tested with two real merchants.
>
> For BOLA, I answer `404` for someone else's order, identical to a nonexistent one, so it does not leak that
> the order exists. I kept guest checkout because the public storefront depended on it, and made it switchable
> through configuration.

**Follow-up questions**

- *Why EdDSA and not HS256?* Because whoever validates (the gateway) should not be able to issue. With an
  asymmetric key the gateway only holds the public key, and rotation happens by `kid` in the JWKS.
- *How do you prevent `alg: none` and algorithm confusion?* I pin `EdDSA` at verification and require `kid`,
  `exp`, `iss`, and `aud`. There are tests with `none`, with HS256 signed using the public key, and with an
  unknown `kid`.
- *A stolen refresh token?* Rotation makes the thief and the owner race for the same token. Whoever arrives
  second triggers revocation of the family, and the session ends for both. There is a concurrency test with six
  requests.
- *What was left out?* MFA and an `HttpOnly` cookie through a BFF. They are listed above, with the reason.
- *How do you revoke a JWT without hitting the database on every call?* Identity stores the `jti` of each access
  token alongside the refresh token that issued it. When the session is revoked, it writes the still-live `jti`s
  to Redis with a TTL equal to their remaining life. The gateway does a cheap lookup with a half-second cache:
  the cost is the cache window and the Redis dependency, with the failure mode chosen in configuration.
- *How do you prove isolation works?* Tests at each layer (in memory, real Postgres) and the e2e, which creates
  two users and two merchants and tries to read what is not theirs.
