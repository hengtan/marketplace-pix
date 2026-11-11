**English** | [Português (Brasil)](pt-BR/DESIGN.md)

# Design direction

## Scene of use

Someone on the couch at night, or on a lunch break, deciding on a purchase on their phone and wanting to pay without friction.
PIX has to feel fast and trustworthy. The merchant checks the balance at the office, on a big screen.
Hence: light and dark themes from day one, 44 px touch targets, and a single path to pay.

## Identity: "praça de noite" (the square at night)

A praça (public square) is a place where things happen. The interface is a living storefront: aurora light in the background, objects floating
in layers, numbers that roll, and a PIX that confirms before your eyes. The contrast comes from two gestures:
large, dense headlines in Bricolage Grotesque, with one word in a serif italic (Instrument Serif) as the
signature ("Pague em *segundos*" (pay in seconds), "Vitrine *completa*" (complete storefront)).

Color, in OKLCH: electric ultramarine for brand and action, mint only for money and confirmation, sun (warm orange) only
in gradients and accents. Light mode is warm paper (`oklch(0.974 0.007 85)`); dark mode is deep ink
(`oklch(0.145 0.032 275)`) with surfaces in lightness steps of 0.04.

| Role | Light | Dark |
|---|---|---|
| Background | `oklch(0.974 0.007 85)` | `oklch(0.145 0.032 275)` |
| Surface | `oklch(0.994 0.003 85)` | `oklch(0.19 0.035 275)` |
| Text | `oklch(0.19 0.045 275)` | `oklch(0.96 0.01 275)` |
| Primary | `oklch(0.49 0.255 270)` | `oklch(0.72 0.17 272)` |
| PIX | `oklch(0.74 0.175 165)` | `oklch(0.82 0.165 165)` |
| Sun | `oklch(0.76 0.17 50)` | `oklch(0.8 0.15 55)` |

All tokens live in `src/index.css` and are switched by the `.dark` class (system by default, persisted,
applied by a script in the `<head>`). The theme switch uses View Transitions.

## Typography

- Display: variable Bricolage Grotesque, width axis at 90, tracking of -0.055em, fluid scale
  (`--text-display` from 2.75 to 7.5 rem via `clamp`).
- Accent: Instrument Serif italic, one word per headline only.
- Interface: variable Geist; numbers use `tabular-nums`. PIX code in Geist Mono.
- Everything is self-hosted through Fontsource, no CDN.

## Surfaces and depth

- Layers: background, `panel` (subtle gradient, 1 px border, inner highlight on top), `glass` (18 px blur, 1.5 saturation).
- Five-layer shadows (`--shadow-lift`) tinted with the brand hue; `--shadow-glow` for the primary action.
- Aurora: three radial blobs in slow drift (`transform` only), a fine grid with a mask, and a fixed fractal noise (SVG,
  rasterized once).
- Radii: 12 px for controls, 20 to 28 px for cards, pills for buttons and filters.

## Product photos without images

`ProductImage` never downloads third-party images. Each product becomes an SVG composition: an OKLCH gradient per category
(base hues 272, 48, and 168) with per-product variation, a dot grid, rings, a hash-positioned glow, a floor shadow, and an
object drawn per keyword (headphones, speaker box, watch, keyboard, lamp, vase, backpack, sneaker, helmet, and 6 more).
Only same-domain URLs (`/...`) are loaded as `<img>`. Weight: zero bytes of images.

## Motion

Motion library, `transform` and `opacity` only (exceptions: `stroke-dashoffset` on the PIX ring and `pathLength` on SVG strokes).

| Moment | Technique |
|---|---|
| Hero | word-by-word text with a mask, layered scene with mouse parallax (spring), scroll-driven (`useScroll` and `useTransform`) |
| Cards | 3D tilt with perspective and a spotlight that follows the cursor, lift on hover |
| Buttons | magnetic (`Magnetic`) on CTAs |
| List to detail | shared-element transition via View Transitions, enabled only on product links (`viewTransition`), falling back to a fade |
| Cart | item flies in an arc to the cart button, spring counter, rows with `AnimatePresence` and `layout` |
| Navigation | active pill with `layoutId`, scroll progress bar, page exits with a fade and rise (180 ms) and enters with a fade and offset |
| Checkout | stepper with a line that fills |
| PIX | QR with a sweep, countdown ring, timeline that fills in real time |
| Payment | confetti (64 pieces, transform only) and a seal with a drawn stroke |
| Dashboard | rolling numbers, sparklines that draw themselves, Recharts charts with animated entry, tab pill with `layoutId`, tabs with a 220 ms exit and entry, staggered rows, heatmap, 3 s highlight on a new sale, coverage bars that grow |
| Marquee | category ticker in pure CSS, pauses on hover |
| Cursor | ring that grows over interactive elements and becomes a "Ver" (view) label on products (fine pointer only) |

`prefers-reduced-motion`: `MotionConfig reducedMotion="user"` turns off transform and layout animations; custom components check
`useReducedMotion` (no parallax, no tilt, no flight, no confetti, static marquee wrapped into lines, shimmer removed);
global CSS zeroes out animations. `will-change` only on layers that animate continuously.

## Merchant dashboard

Lazy route `/lojista`, each tab is its own chunk (Recharts is still loaded only on the overview). State goes into the URL: `?aba=visao-geral|pedidos|estoque|produtos|extrato`, `dias=7|14|30` (preserved when switching tabs), `loja` (admin), `pedido=<id>` (drawer open), and `novo=true` (product form). Invalid values fall back to the default instead of breaking the route. Changing only the query does not redo the session refresh, clear toasts, or move focus (`pathChanged` in `onResolved`).

| Tab | What it shows | API |
|---|---|---|
| Overview (Visão geral) | 6 KPIs (balance, gross, net, orders, average ticket, effective rate) with change against the previous period, actionable alerts, sales per day with optional moving average and a rich tooltip, orders per day, heat calendar and average per weekday, best day | `GET /api/ledger/merchants/{id}/summary` twice: `days` (totals and balance) and `days*2` (only `daily`, split into two halves) |
| Orders (Pedidos) | dense table, status filter, search (customer, product, code), pagination of 10, drawer with items, 10% fee, net amount, and timeline, refresh every 10 s with a toast and a highlight on a new sale | `GET /api/orders/merchant` (up to 4 pages of 50) |
| Stock (Estoque) | available, reserved, coverage bar (stock divided by the pace of the last 14 days), status, inline editing with validation, optimistic update and rollback, bulk action | `GET /api/inventory/stock/mine`, `PUT /api/inventory/stock/{id}` (admin: `GET /api/inventory/stock?product_ids=`) |
| Products (Produtos) | cards, create and edit with a validated form (zod), deactivate with confirmation | `POST`, `PATCH`, `DELETE /api/catalog/products` |
| Statement (Extrato) | type filter, grouping by day, running balance, CSV export, copy value | `GET /api/ledger/accounts/merchant:{id}/entries` (up to 4 pages of 100) |

Business rules on the client, all in `src/lib/merchant-metrics.ts` (pure functions, with tests): percentage change (a zero base becomes "sem base" (no baseline), never a division by zero), moving average, aggregation by weekday, calendar grid, order filters, detection of a new or paid order between two reads, stock coverage and level (out of stock, critical at 5 units or fewer or under 3 days, warning up to 7 days), alerts (stock, PIX stalled for more than 5 minutes, a drop of 20% or more), running balance, grouping by day, and CSV (BOM, `;`, quotes, and formula injection protection).

The real contract as observed on the gateway, and how the dashboard handles it:

- `GET /orders/merchant` returns `subtotal_cents` and only the merchant's items, with no customer email or product name: names come from the store's product list and the email is not displayed.
- An `admin` account has no store: `orders/merchant` and `stock/mine` respond 403. The Orders tab explains this without calling the API, and Stock uses the public read with `reserved`.
- Maximum `page_size` of 50 for orders. The dashboard warns when it is showing only the most recent ones.
- A write without scope or on someone else's product returns 403, and the dashboard shows the message instead of failing silently: stock errors become a toast and a rollback, catalog errors appear in the form. A duplicate name (409) becomes a field error.
- Deactivation is reversible. The Products tab lists the owner's deactivated products in a "Desativados" (deactivated) section, fed by `GET /catalog/products/mine`, each with a Reactivate button. The stock quantity is preserved. If an account can read but not write, the dashboard falls back to the public list, which shows active products only.
- A new product gets its inventory row asynchronously, from the `ProductCreated` event (usually within a fraction of a second). The dashboard waits briefly and retries the initial stock `PUT` (`retryUntilReady`), and only warns "Produto criado, ainda sem estoque" if it still cannot save it.
- Catalog reads revalidate on every request (ETag, `Cache-Control: max-age=0, must-revalidate`) and the owner list is `no-store`, so an edit, a new product or a deactivation shows up immediately and the screen never "goes back in time".

Shortcuts (outside text fields and with no dialog open): `g` then `v`, `p`, `e`, `r` (products) or `x`; `n` new product; `/` tab search; `?` help. The ⌘K palette gains "Ir para ..." (go to) for each tab and "Novo produto" (new product) for merchant and admin accounts, keeping the period and store when already on the dashboard.

Tab accessibility: `tablist` with arrow keys, Home and End, labeled `tabpanel`, counters with hidden text, tables with captions, `rowgroup` in the statement, calendar as a table, `meter` for coverage, drawer and dialogs with a focus trap, Esc, and focus return. The e2e suite runs axe on every tab in both themes, on the drawers, and on the dialogs.

## Layout

- Two-column hero with the scene on the right; categories as cards with artwork; storefront in 2, 3, and 4 columns.
- Single-screen checkout with a sticky summary; order page with the PIX panel and timeline.
- Responsive from 360 px to 4K (80 rem container, fluid typography).

## Authentication

`/entrar` and `/cadastro` with a showcase panel and a glass form. Contract used (MSW mock in `src/mocks/auth.ts`):
`POST /api/auth/register` and `POST /api/auth/login` return `{access_token, refresh_token, token_type, expires_in, user}`;
`POST /api/auth/refresh`; `GET /api/auth/me`. The HTTP client sends `Authorization: Bearer`, refreshes once on a 401
(a single shared request), and clears the session if the refresh fails. `/lojista` and `/conta` are protected (they redirect
to `/entrar?redirect=...`); `/lojista` also requires the `merchant` role. The whole store remains browsable as a guest.
The `access_token` lives in memory only (Zustand without persistence). The `refresh_token` is the only thing persisted, in `sessionStorage` (key `praca-rt`), and it rotates on every refresh. On load, `restoreSession` does a silent refresh (shared, once only, since replaying an old refresh token revokes the session) and fetches `/api/auth/me`; protected routes wait for this step. Signing out calls `POST /api/auth/logout` and clears everything. The old `praca-auth` key in `localStorage` is removed. The production recommendation (httpOnly cookie via a BFF) is in `docs/AUTH-TOKENS.md`.

Access states: a 401 that cannot be refreshed clears the session and, on `/conta` and `/lojista`, redirects to `/entrar?redirect=<destination>` with a notice; a 403 shows "Você não tem acesso a esta área" (you do not have access to this area) with a way out to another account or to the store (`ErrorState` with `error`).

## Shopping assistant

Glass button with an orb (spinning conic gradient). The orb speeds up and pulses while the assistant is thinking, and particles
rise in the empty state. Messages enter with a fade and rise, the panel is lazy loaded and preloaded
when idle. The chat sends `Authorization: Bearer` when there is a session (refreshing on a 401). Friendly errors: budget 429 (`budget exceeded`, scope `session` or `user`) with no retry button and with the `Retry-After` time; plain 429 and 503 with a countdown on the "Tentar de novo" (try again) button; a degraded response (`warning` in SSE or `degraded` in `done`) gets a `role=status` notice. The remaining accessibility and content rules stay as they were.

## States

Empty, error, and loading states have their own animated SVG illustrations (`illustrations.tsx`): cart, search, orders, error,
lost page, and PIX. Skeletons use a `transform`-based shimmer.

## Accessibility

AA contrast in both themes (axe on store, product, order, orders, the five merchant tabs, sign-in, and sign-up), visible 2 px focus,
skip link, landmarks, focus moved to the content on every route, `aria-live` for PIX and copy, table with caption,
charts with a text summary, animated text with an `sr-only` copy.

## Performance

Measurement: production build under `vite preview` (proxy to the real gateway), Lighthouse 12 in mobile mode (slow 4G, 4x CPU, simulated), 5 runs per page, Playwright's Chromium.

| Page | Before (performance) | After (performance) |
|---|---|---|
| Home | 84 to 85 (LCP 3.7 s, FCP 2.6 s, TBT 80 ms) | 88 to 91, median 89 (LCP 3.0 to 3.2 s, FCP 2.6 s, TBT 50 to 160 ms, CLS 0) |
| Product | 82 to 83 (LCP 4.0 s, FCP 2.7 s, TBT 100 to 140 ms) | 87 to 88 (LCP 3.3 s, FCP 2.7 s, TBT 30 to 50 ms, CLS 0.003) |

The target of 90 did not hold steadily in the simulated lab: the floor is the JS needed to render (React, router, Query, Motion, ~199 kB gzip versus ~275 kB before). Measured with real Chromium throttling (CDP), the home LCP dropped from 4.1 s to 1.1 s thanks to the static shell.

What changed, in order of gain:

- Initial JS from ~275 to ~199 kB gzip: Motion in `LazyMotion` with `m` and features (`domMax`) loaded separately; `zod/mini`; Sonner, the user menu (Radix), the bell, the cursor, the assistant panel, the cart, and the palette moved off the critical path, loaded on first interaction or after 6 s; the bell only for signed-in users.
- Page entry no longer hides content on first load (`AnimatePresence initial={false}`): with Motion's features loading asynchronously, the initial `opacity: 0` delayed LCP by ~1.2 s.
- Static home shell in `index.html` (pill, title, and hero text with the same classes). The app mounts only after first paint (`afterFirstPaint`) and skips the entry animation for what is already on screen. A check in `src/lib/shell.test.ts` keeps the text identical to `Hero`.
- Product: the product fetch is started by an inline script in the `<head>` and reused by the client (`window.__early`); the product page is loaded with the main bundle (2.5 kB); related products only after 900 ms.
- The TanStack Router initial view transition (`defaultViewTransition`) was turned off: it wrapped the first render. Now only product links use `viewTransition`.
- Fonts: Bricolage Grotesque re-exported with `wdth` fixed at 90 and Latin only (41 kB, down from 78 kB, same design), preload only on the home page (Geist, Bricolage, and Instrument Serif; the serif avoids a CLS of 0.17), no preload on the other routes.
- Infinite animations (brand, chips, and orb) moved from per-frame JS to CSS keyframes on the compositor.
- The ⌘K palette does not fetch orders until it opens.
- Tested and discarded: `manualChunks`/`codeSplitting` by groups (worse), a newer `build.target` (no gain), lazy `HomePage` (-2.5 kB, one more round trip on the home page).

### Exit transition between pages

`AnimatePresence mode="wait"` wraps the route content in `AppShell`. Freezing the `Outlet` during the exit is not possible in this version of TanStack Router (matches come from stores, and the old route's exit zeroes out its store). So navigation is held back: the root `beforeLoad` starts the exit (`src/lib/route-transition.ts`), the old content fades and rises 10 px in 180 ms, `onExitComplete` releases the navigation, and the new page enters. It does not fire on preload, on a query-only change, under `prefers-reduced-motion`, or between list and product. Focus goes to `#conteudo` and scroll returns to the top on resolve, as before; there is a 700 ms fallback. Covered by e2e (minimum opacity, focus, scroll, axe, reduced motion).

### Shared element from list to product

View Transitions was kept. Motion's `layoutId` needs the old and new elements to exist at the same time under an `AnimatePresence`, and for the reason above the old route does not stay mounted. View Transitions captures the DOM before and after the swap, works without keeping the old route in the tree, runs on the compositor, and costs 0 kB of JS. No regression measured: initial JS went down and Lighthouse does not depend on it (it only runs on navigation).

### Dashboard and initial JS

The dashboard is a lazy route, and its API (`src/api/merchant.ts`) and formatters (`src/lib/format-merchant.ts`) stay out of the initial bundle. Measured with `pnpm build` (sum of the gzip of what `index.html` loads): 199.0 kB before, 199.2 kB after (+0.2 kB, the route's search params schema and the `onResolved` adjustment).

## Copy

pt-BR, no em dashes, short sentences, direct verbs. Footer: "Engineering by MocktStudio" linking to
https://mocktstudio.com.
