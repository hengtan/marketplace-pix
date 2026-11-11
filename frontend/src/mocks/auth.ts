import { delay, HttpResponse, http } from "msw";
import type { User } from "@/api/schemas";
import { env } from "@/lib/env";

const base = env.apiUrl.replace(/\/$/, "");
const url = (path: string) => `${base}${path}`;

interface Account extends User {
  password: string;
  readOnly?: boolean;
}

const SEEDED = new Set([
  "lojista@praca.dev",
  "cliente@praca.dev",
  "admin@praca.dev",
  "leitura@praca.dev",
]);

const TRILHA = "435c5a06-d955-566e-9daf-776be4040c6f";
const AURORA = "1748b018-c69c-53e3-a29d-762cd894d4ff";

const accounts = new Map<string, Account>([
  [
    "lojista@praca.dev",
    {
      id: "6f1d1c36-6b0a-5a39-8f8e-0b8d2a4a1001",
      email: "lojista@praca.dev",
      name: "Lívia Prado",
      roles: ["customer", "merchant"],
      merchant_id: TRILHA,
      password: "praca1234",
    },
  ],
  [
    "admin@praca.dev",
    {
      id: "6f1d1c36-6b0a-5a39-8f8e-0b8d2a4a1003",
      email: "admin@praca.dev",
      name: "Administrador",
      roles: ["admin"],
      merchant_id: null,
      password: "praca1234",
    },
  ],
  [
    "leitura@praca.dev",
    {
      id: "6f1d1c36-6b0a-5a39-8f8e-0b8d2a4a1004",
      email: "leitura@praca.dev",
      name: "Rui Leitura",
      roles: ["merchant"],
      merchant_id: AURORA,
      readOnly: true,
      password: "praca1234",
    },
  ],
  [
    "cliente@praca.dev",
    {
      id: "6f1d1c36-6b0a-5a39-8f8e-0b8d2a4a1002",
      email: "cliente@praca.dev",
      name: "Caio Martins",
      roles: ["customer"],
      password: "praca1234",
    },
  ],
]);

const ACCESS_TTL = 900;
const SESSIONS_KEY = "praca-mock-sessions";
const ACCOUNTS_KEY = "praca-mock-accounts";

const PERSIST = import.meta.env.MODE !== "test";

function restore<T>(key: string): [string, T][] {
  if (!PERSIST) return [];
  try {
    return JSON.parse(localStorage.getItem(key) ?? "[]") as [string, T][];
  } catch {
    return [];
  }
}

function persist(key: string, map: Map<string, unknown>) {
  if (!PERSIST) return;
  try {
    localStorage.setItem(key, JSON.stringify([...map]));
  } catch {
    /* storage unavailable */
  }
}

const sessions = new Map<string, string>(restore<string>(SESSIONS_KEY));
for (const [email, account] of restore<Account>(ACCOUNTS_KEY)) accounts.set(email, account);

function lookup(token: string | undefined): string | undefined {
  if (!token) return undefined;
  return sessions.get(token) ?? new Map(restore<string>(SESSIONS_KEY)).get(token);
}

function publicUser({ password: _password, readOnly: _readOnly, ...user }: Account): User {
  return { merchant_id: null, ...user };
}

export type MockAccount = Account;

function issue(account: Account) {
  const access = `acc.${crypto.randomUUID()}`;
  const refresh = `ref.${crypto.randomUUID()}`;
  sessions.set(access, account.email);
  sessions.set(refresh, account.email);
  persist(SESSIONS_KEY, sessions);
  return {
    access_token: access,
    refresh_token: refresh,
    token_type: "bearer",
    expires_in: ACCESS_TTL,
    user: publicUser(account),
  };
}

export function bearer(request: Request): Account | null {
  const token = request.headers.get("Authorization")?.replace(/^Bearer /, "");
  const email = lookup(token);
  return email ? (accounts.get(email) ?? null) : null;
}

export const authHandlers = [
  http.post(url("/api/auth/register"), async ({ request }) => {
    await delay(500);
    const body = (await request.json()) as { name: string; email: string; password: string };
    const email = body.email.trim().toLowerCase();
    if (accounts.has(email))
      return HttpResponse.json({ detail: "Este e-mail já está cadastrado" }, { status: 409 });
    if (body.password.length < 8)
      return HttpResponse.json(
        { detail: "A senha precisa ter 8 caracteres ou mais" },
        { status: 422 },
      );
    const account: Account = {
      id: crypto.randomUUID(),
      email,
      name: body.name.trim(),
      roles: ["customer"],
      password: body.password,
    };
    accounts.set(email, account);
    persist(ACCOUNTS_KEY, new Map([...accounts].filter(([k]) => !SEEDED.has(k))));
    return HttpResponse.json(issue(account), { status: 201 });
  }),

  http.post(url("/api/auth/login"), async ({ request }) => {
    await delay(500);
    const body = (await request.json()) as { email: string; password: string };
    const account = accounts.get(body.email.trim().toLowerCase());
    if (!account || account.password !== body.password)
      return HttpResponse.json({ detail: "E-mail ou senha incorretos" }, { status: 401 });
    return HttpResponse.json(issue(account));
  }),

  http.post(url("/api/auth/refresh"), async ({ request }) => {
    const body = (await request.json()) as { refresh_token: string };
    const email = lookup(body.refresh_token);
    const account = email ? accounts.get(email) : undefined;
    sessions.delete(body.refresh_token);
    persist(SESSIONS_KEY, sessions);
    if (!account) return HttpResponse.json({ detail: "Sessão expirada" }, { status: 401 });
    const { access_token, refresh_token, token_type, expires_in } = issue(account);
    return HttpResponse.json({ access_token, refresh_token, token_type, expires_in });
  }),

  http.post(url("/api/auth/logout"), async ({ request }) => {
    const body = (await request.json()) as { refresh_token?: string };
    if (body.refresh_token) sessions.delete(body.refresh_token);
    persist(SESSIONS_KEY, sessions);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(url("/api/auth/me"), async ({ request }) => {
    await delay(150);
    const account = bearer(request);
    if (!account) return HttpResponse.json({ detail: "Não autenticado" }, { status: 401 });
    return HttpResponse.json(publicUser(account));
  }),
];
