**English** | [Português (Brasil)](pt-BR/AUTH-TOKENS.md)

# Authentication tokens in the browser

## How it works today

- `access_token` (JWT, 10 min): in memory only, in the non-persisted Zustand store. It disappears on reload.
- `refresh_token` (opaque, rotating): `sessionStorage`, key `praca-rt`, and nowhere else. On load, a shared silent refresh returns a new access token and `GET /api/auth/me` returns the profile.
- Every refresh swaps the refresh token (the old one dies). That is why only one refresh is in flight at a time and it never runs inside a React effect.
- Signing out calls `POST /api/auth/logout` (revokes the session) and clears the storage. The legacy `localStorage["praca-auth"]` is removed at boot.
- `sessionStorage` is per tab: another tab asks for sign-in again. This is the smallest possible surface without a new backend. `localStorage` would share the session across tabs, but it exposes the refresh token to any XSS for longer.

Limitation of this approach: an XSS can still read the refresh token while the tab is open.

## Production recommendation: httpOnly cookie via a BFF

1. A BFF on the same origin as the SPA (for example nginx itself with a thin service) handles `login` and `refresh`, stores the refresh token in a `HttpOnly; Secure; SameSite=Strict; Path=/api/auth` cookie, and returns only the access token to the browser.
2. The SPA calls `POST /api/auth/refresh` with no body; the cookie goes along on its own. JS never sees the refresh token.
3. CSRF: `SameSite=Strict` plus a mandatory custom header (`X-Requested-With`) on session routes.
4. Rotation with reuse detection stays in identity (replaying a used refresh token revokes the session).
5. On the frontend the change is small: `refreshSession` stops reading and writing the token, and `store/auth.ts` loses `writeRefresh`.
