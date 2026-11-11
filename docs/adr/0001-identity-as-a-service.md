**English** | [Português (Brasil)](../pt-BR/adr/0001-identidade-como-servico.md)

# ADR 0001: identity as its own service (`identity`, port 8008)

Status: accepted.

## Context

The system had no authentication or authorization: any client could read any order, change stock, and see any
merchant's ledger. We need sign-up, login, tokens, roles, and isolation between merchants. The decision is where
to put the identity responsibility: inside the gateway (as a module) or in a new service.

## Decision

A separate `identity` service with its own database (`identity`) that owns credentials, tokens, and keys.
The gateway holds no identity state: it only **validates** the JWT (signature, `iss`, `aud`, `exp`) using the
`identity` public key (JWKS) and injects a **signed** identity (HMAC) into upstream requests, which the services
trust. The gateway code that handles this lives in new modules (`gateway/auth/`).

Security choices:

- Short-lived JWT access token (10 minutes), signed with **EdDSA (Ed25519)**, with a `kid` in the header and a
  public JWKS. The algorithm is pinned at verification time (no `none`, no HS256 with the public key).
- **Opaque**, rotating refresh token, stored only as a SHA-256 hash. Each use issues a new one; presenting an
  already-used token revokes the entire family (theft detection). A session has an absolute lifetime of 30 days.
- Passwords use **argon2id**. Login timing is equalized for unknown emails, with a temporary lockout per account.
- Roles (`customer`, `merchant`, `admin`) map to **scopes** (`orders:create`, `ledger:read:own`, ...). The
  merchant carries `merchant_id` in the token: it is the source of the tenant, never a client-supplied parameter.
- Defense in depth: the gateway applies a per-route policy (anonymous, optional, required + scope), and each
  service **re-applies** object-level authorization (owner's order, merchant's ledger, merchant's stock),
  because the service ports are also published on the host.

## Why not a module inside the gateway

| Criterion | Module in the gateway | `identity` service |
|---|---|---|
| Attack surface | The edge proxy ends up holding password hashes and the private key | The proxy only holds the public key |
| State | The gateway stops being stateless (database, migrations) | The gateway scales horizontally with no state |
| Blast radius | A proxy failure affects credentials | Credentials are isolated, with their own database and deploy |
| Key rotation | Coupled to the gateway deploy | The JWKS publishes the new and old keys at the same time |
| Cost | Lower (one fewer process) | One more service, plus one cached JWKS call |

The extra cost is small (one more service following the pattern the repository already uses), and the gain is
separating whoever **issues** trust from whoever **forwards** requests.

## Consequences

- The service ports remain published, so the identity coming from the gateway is **signed** and bound to the
  `X-Request-Id` and a timestamp (60 s). Forged `X-User-*` headers are worthless, and the gateway strips any the
  client sends.
- If the JWKS is unavailable, requests carrying a token fail closed (503); anonymous requests continue.
- The access token cannot be revoked before it expires (10 minutes). That is the price of validating without a
  database lookup.
- The refresh token travels in the response body. A production frontend should store it in an `HttpOnly` cookie.
- Guest checkout still exists (an order with no owner, accessible to anyone who has the id). It can be turned off
  with `ALLOW_GUEST_CHECKOUT=false` on the gateway.
