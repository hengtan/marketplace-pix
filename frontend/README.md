**English** | [Português (Brasil)](README.pt-BR.md)

# Praça, the marketplace PIX frontend

Storefront, PIX checkout, and merchant dashboard. React 19, Vite, strict TypeScript, Tailwind CSS v4,
TanStack Router and Query, Zustand, React Hook Form with Zod, Motion, cmdk, Recharts.
The SPA talks only to the gateway (`/api/...`), as defined in `docs/CONTRACTS.md`.

## Running it

Requirements: Node 22+ and pnpm.

```bash
pnpm install

# 1) Standalone, with contract-faithful mocks (MSW) and state persisted in localStorage
pnpm dev:mock            # http://localhost:5173

# 2) Against the real backend (gateway at http://localhost:8000)
cp .env.example .env     # adjust VITE_API_URL if needed
pnpm dev                 # http://localhost:5173
```

To try the simulation tool against the real backend, use `VITE_ENABLE_DEV_TOOLS=true pnpm dev`.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Gateway base URL. Empty in Docker (uses the nginx proxy, same origin) |
| `VITE_USE_MOCKS` | `false` | `true` enables MSW and every contract endpoint with in-memory state |
| `VITE_ENABLE_DEV_TOOLS` | `false` | `true` shows the "Simular pagamento" (simulate payment) button on the PIX panel |
| `VITE_PROXY_TARGET` | empty | `pnpm dev` only: forwards Vite's `/api` to the gateway (use it with an empty `VITE_API_URL` to avoid CORS on another port) |

## Scripts

| Script | What it does |
|---|---|
| `pnpm dev` / `pnpm dev:mock` | Development server (real backend / mocks) |
| `pnpm build` | Typecheck and production build into `dist/` |
| `pnpm typecheck` | Strict `tsc` |
| `pnpm lint` / `pnpm format` | Biome |
| `pnpm test` | Vitest (unit and component tests) |
| `pnpm e2e` | Playwright with mocks (purchase flow, command palette, theme, axe) |
| `pnpm screenshots` | Regenerates `docs/screenshots/` |

On the first Playwright run: `pnpm exec playwright install chromium`.

## Demo scenarios with the mocks

- Full purchase: cart, checkout, QR code, "Simular pagamento" (simulate payment), success.
- Expired PIX: use an email or name containing `expira` (the PIX expires in 25 s and the order is canceled with `payment expired`).
- Insufficient stock: `relogio-gps-trail` has 3 units and `smartwatch-orbit` has 5. Order more than what is available
  (for example by lowering the stock through `PUT /api/inventory/stock/{id}` or by buying twice) and the order is canceled with `out of stock`.
- Listing error: searching for `__erro` returns a 500.
- To reset the mock state, clear the site's `localStorage`.

## Shopping assistant

The floating button (bottom right corner), the ⌘K palette ("Perguntar ao assistente" or "Perguntar: your text") and the
`Ctrl /` shortcut (`⌘ /` on Mac) open the chat. Esc closes it and focus returns to the button.

- Streaming: `POST /api/assistant/chat/stream` is read with `fetch` and an SSE parser that tolerates split chunks
  (`src/features/assistant/sse.ts`). `tool_call` events become live states, `token` builds the text, and `done` carries the session,
  citations, and trace. The stop button uses `AbortController`, and there is a 45 s timeout when no events arrive.
- Answers: a custom, safe renderer (bold, lists, line breaks, `[1]` chips linking to `/produto/:slug`) with no
  `dangerouslySetInnerHTML`. Cited products appear as cards with price and "Adicionar" (add).
- "Como cheguei nessa resposta" (how I got this answer): tools called (arguments, summary, duration) and retrieved passages with score and
  latency, in a timeline.
- Session in `localStorage` (`praca-assistant-session`), reloaded through `GET /api/assistant/sessions/{id}`.
  "Nova conversa" (new conversation) clears everything.
- Mocks (`src/mocks/assistant.ts`) simulate SSE with `tool_call`, citations, and trace. Test phrases: `simular erro`
  (`error` event), `simular limite` and `simular limite da sessao` (budget 429), `simular muitas` (429), `simular indisponivel` (503), `simular degradado` (partial-answer warning), and `resposta lenta` (slow tokens, good for testing the stop button).
- Against the real backend on another port: `VITE_PROXY_TARGET=http://localhost:8000 VITE_API_URL= pnpm exec vite --port 5174`.
- In nginx, `/api/assistant/chat/stream` has `proxy_buffering off` so text arrives token by token.

Screenshot at `docs/screenshots/07-assistente-escuro.png`.

## Account and protected routes

`/entrar` (sign in) and `/cadastro` (sign up) talk to `POST /api/auth/login`, `POST /api/auth/register`, `POST /api/auth/refresh`, and
`GET /api/auth/me` (MSW mock with the accounts `lojista@praca.dev` and `cliente@praca.dev`, password `praca1234`). `/lojista` and `/conta`
require a session; the store stays open to guests. The access token lives in memory and the refresh token in `sessionStorage` (silent renewal on load); details and the httpOnly cookie recommendation are in `docs/AUTH-TOKENS.md`. The HTTP client refreshes once on a 401 and, if it cannot refresh, sends the user to sign-in while preserving the destination.

## Performance

Before and after numbers, and what changed, are in `docs/DESIGN.md` (Performance section). Summary: simulated mobile (slow 4G, 4x CPU) home 88 to 91 and product 87 to 88 (before 84 to 85 and 82 to 83), initial JS ~199 kB gzip. Recharts (~111 kB gzip) only loads on the dashboard.

## Docker

```bash
docker build -t marketplace-pix-frontend .
docker run --rm -p 8080:80 -e API_UPSTREAM=http://host.docker.internal:8000 marketplace-pix-frontend
```

Multi-stage build: Node compiles and nginx serves the SPA with a fallback to `index.html` and a proxy from `/api/` to
`API_UPSTREAM` (default `http://gateway:8000`). `GET /healthz` returns `ok`.

## Structure

```
src/
  api/        typed client, Zod schemas, and contract endpoints
  mocks/      seed data, in-memory database (idempotency, saga, ledger), and MSW handlers
  hooks/      TanStack Query queries and useOrderStatus (2 s polling, swappable for SSE)
  store/      cart (persisted), customer, theme, UI
  components/ reusable components and UI base (Radix)
  features/   PIX panel, timeline, hero, assistant (chat, SSE, trace)
  pages/      routes (lazy loaded)
docs/         DESIGN.md, AUTH-TOKENS.md, and screenshots
e2e/          Playwright
```

## Decisions

- `customer_id` is a uuid saved in `localStorage`. The `Idempotency-Key` is generated per checkout attempt
  (signature of items and email) and kept until success, so retries after a network failure do not duplicate the order.
- The email preview fetches `/api/notifications/{id}/preview` and renders it in an `iframe` with an empty `sandbox`.
- `GET /products/by-ids` is read as a paginated envelope, matching the current version of the contract.
