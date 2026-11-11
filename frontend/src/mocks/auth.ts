import { delay, HttpResponse, http } from "msw";
import type { User } from "@/api/schemas";
import { env } from "@/lib/env";

const base = env.apiUrl.replace(/\/$/, "");
const url = (path: string) => `${base}${path}`;

interface Account extends User {
  password: string;
}

const accounts = new Map<string, Account>([
  [
    "lojista@praca.dev",
    {
      id: "6f1d1c36-6b0a-5a39-8f8e-0b8d2a4a1001",
      email: "lojista@praca.dev",
      name: "Lívia Prado",
      roles: ["customer", "merchant"],
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
const sessions = new Map<string, string>();

function publicUser({ password: _password, ...user }: Account): User {
  return user;
}

function issue(account: Account) {
  const access = `acc.${crypto.randomUUID()}`;
  const refresh = `ref.${crypto.randomUUID()}`;
  sessions.set(access, account.email);
  sessions.set(refresh, account.email);
  return {
    access_token: access,
    refresh_token: refresh,
    token_type: "bearer",
    expires_in: ACCESS_TTL,
    user: publicUser(account),
  };
}

function bearer(request: Request): Account | null {
  const token = request.headers.get("Authorization")?.replace(/^Bearer /, "");
  const email = token ? sessions.get(token) : undefined;
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
    const email = sessions.get(body.refresh_token);
    const account = email ? accounts.get(email) : undefined;
    if (!account) return HttpResponse.json({ detail: "Sessão expirada" }, { status: 401 });
    const { access_token, refresh_token, token_type, expires_in } = issue(account);
    return HttpResponse.json({ access_token, refresh_token, token_type, expires_in });
  }),

  http.get(url("/api/auth/me"), async ({ request }) => {
    await delay(150);
    const account = bearer(request);
    if (!account) return HttpResponse.json({ detail: "Não autenticado" }, { status: 401 });
    return HttpResponse.json(publicUser(account));
  }),
];
