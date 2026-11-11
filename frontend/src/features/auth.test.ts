import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { parseRetryAfter, request, toError } from "@/api/client";
import { api } from "@/api/endpoints";
import { userSchema } from "@/api/schemas";
import { env } from "@/lib/env";
import { setSessionExpiredHandler } from "@/lib/session";
import { server } from "@/mocks/server";
import { useAuth } from "@/store/auth";
import { loginSchema, passwordScore, registerSchema, safeRedirect } from "./auth-schema";
import { restoreSession, signOut } from "./session";

const url = (p: string) => `${env.apiUrl.replace(/\/$/, "")}${p}`;

describe("auth schemas", () => {
  it("rejects weak registrations in pt-BR", () => {
    const r = registerSchema.safeParse({ name: "A", email: "x", password: "123" });
    expect(r.success).toBe(false);
    expect(loginSchema.safeParse({ email: "a@b.co", password: "x" }).success).toBe(true);
  });

  it("scores passwords from weak to strong", () => {
    expect(passwordScore("abc")).toBe(0);
    expect(passwordScore("abcdefg1")).toBeGreaterThanOrEqual(2);
    expect(passwordScore("Abcdefghij1!")).toBe(4);
  });

  it("only allows same-site redirects", () => {
    expect(safeRedirect("/lojista")).toBe("/lojista");
    expect(safeRedirect("//evil.com")).toBe("/");
    expect(safeRedirect("https://evil.com")).toBe("/");
    expect(safeRedirect(undefined)).toBe("/");
  });
});

describe("session handling", () => {
  beforeEach(() => useAuth.getState().clear());

  it("logs in against the mock and stores the session", async () => {
    const res = await api.login({ email: "lojista@praca.dev", password: "praca1234" });
    useAuth.getState().setSession(res);
    expect(useAuth.getState().user?.roles).toContain("merchant");
    expect((await api.me()).email).toBe("lojista@praca.dev");
  });

  it("refreshes once on 401 and retries", async () => {
    const res = await api.login({ email: "cliente@praca.dev", password: "praca1234" });
    useAuth.getState().setSession({ ...res, access_token: "expired" });
    const me = await api.me();
    expect(me.email).toBe("cliente@praca.dev");
    expect(useAuth.getState().accessToken).not.toBe("expired");
  });

  it("clears the session when the refresh token is rejected", async () => {
    server.use(http.post(url("/api/auth/refresh"), () => HttpResponse.json({}, { status: 401 })));
    useAuth.getState().setSession({
      access_token: "expired",
      refresh_token: "bad",
      token_type: "bearer",
      expires_in: 10,
      user: { id: "1", email: "a@b.co", name: "A B", roles: [] },
    });
    await expect(api.me()).rejects.toThrow();
    expect(useAuth.getState().accessToken).toBeNull();
  });
});

describe("token storage", () => {
  beforeEach(() => {
    useAuth.getState().clear();
    localStorage.clear();
    sessionStorage.clear();
  });

  it("keeps the access token in memory and only the refresh token in sessionStorage", async () => {
    const res = await api.login({ email: "cliente@praca.dev", password: "praca1234" });
    useAuth.getState().setSession(res);

    expect(sessionStorage.getItem("praca-rt")).toBe(res.refresh_token);
    expect(sessionStorage.length).toBe(1);
    expect(localStorage.length).toBe(0);
    const everything = JSON.stringify({ ...sessionStorage, ...localStorage });
    expect(everything).not.toContain(res.access_token);
    expect(everything).not.toContain(res.user.email);
  });

  it("rotates the stored refresh token on every renewal", async () => {
    const res = await api.login({ email: "cliente@praca.dev", password: "praca1234" });
    useAuth.getState().setSession({ ...res, access_token: "expired" });
    await api.me();
    const rotated = sessionStorage.getItem("praca-rt");
    expect(rotated).not.toBeNull();
    expect(rotated).not.toBe(res.refresh_token);
    expect(useAuth.getState().refreshToken).toBe(rotated);
  });

  it("restores the session silently from the stored refresh token", async () => {
    const res = await api.login({ email: "lojista@praca.dev", password: "praca1234" });
    useAuth.getState().setSession(res);
    useAuth.setState({ user: null, accessToken: null, expiresAt: 0 });

    await restoreSession();

    expect(useAuth.getState().accessToken).toBeTruthy();
    expect(useAuth.getState().accessToken).not.toBe(res.access_token);
    expect(useAuth.getState().user?.email).toBe("lojista@praca.dev");
    expect(useAuth.getState().restoring).toBe(false);
  });

  it("starts as a guest when the stored refresh token was revoked", async () => {
    useAuth.setState({ refreshToken: "ref.revoked", accessToken: null, user: null });
    sessionStorage.setItem("praca-rt", "ref.revoked");

    await restoreSession();

    expect(useAuth.getState().accessToken).toBeNull();
    expect(useAuth.getState().user).toBeNull();
    expect(sessionStorage.getItem("praca-rt")).toBeNull();
  });

  it("removes the old localStorage session on boot", async () => {
    localStorage.setItem("praca-auth", JSON.stringify({ state: { accessToken: "old" } }));
    await restoreSession();
    expect(localStorage.getItem("praca-auth")).toBeNull();
  });

  it("signs out by revoking the refresh token and wiping storage", async () => {
    const res = await api.login({ email: "cliente@praca.dev", password: "praca1234" });
    useAuth.getState().setSession(res);

    await signOut();

    expect(useAuth.getState().accessToken).toBeNull();
    expect(sessionStorage.length).toBe(0);
    const reuse = await fetch(`${env.apiUrl.replace(/\/$/, "")}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: res.refresh_token }),
    });
    expect(reuse.status).toBe(401);
  });

  it("tells the app when the session can no longer be renewed", async () => {
    let expired = 0;
    setSessionExpiredHandler(() => {
      expired++;
    });
    server.use(http.post(url("/api/auth/refresh"), () => HttpResponse.json({}, { status: 401 })));
    useAuth.getState().setSession({
      access_token: "expired",
      refresh_token: "bad",
      token_type: "bearer",
      expires_in: 10,
      user: { id: "1", email: "a@b.co", name: "A B", roles: [] },
    });
    await expect(request("/api/auth/me", { schema: userSchema })).rejects.toMatchObject({
      status: 401,
    });
    expect(expired).toBe(1);
    setSessionExpiredHandler(null);
  });
});

describe("error metadata", () => {
  it("reads Retry-After in seconds and as a date", () => {
    expect(parseRetryAfter("30")).toBe(30);
    expect(parseRetryAfter("1.2")).toBe(2);
    expect(parseRetryAfter(null)).toBeUndefined();
    expect(parseRetryAfter("soon")).toBeUndefined();
    const inTenSeconds = new Date(Date.now() + 10_000).toUTCString();
    expect(parseRetryAfter(inTenSeconds)).toBeGreaterThanOrEqual(9);
  });

  it("keeps the budget scope, limit and Retry-After of a 429", async () => {
    const res = new Response(
      JSON.stringify({ detail: "budget exceeded", scope: "user", limit: "tokens" }),
      { status: 429, headers: { "Retry-After": "3600" } },
    );
    const err = await toError(res);
    expect(err).toMatchObject({
      status: 429,
      message: "budget exceeded",
      scope: "user",
      limit: "tokens",
      retryAfter: 3600,
    });
  });

  it("falls back to retry_after_seconds in the body for circuit breaker 503s", async () => {
    const res = new Response(
      JSON.stringify({ detail: "unavailable", code: "circuit_open", retry_after_seconds: 10 }),
      { status: 503 },
    );
    expect(await toError(res)).toMatchObject({ code: "circuit_open", retryAfter: 10 });
  });
});
