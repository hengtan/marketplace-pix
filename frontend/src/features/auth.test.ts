import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { api } from "@/api/endpoints";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { useAuth } from "@/store/auth";
import { loginSchema, passwordScore, registerSchema, safeRedirect } from "./auth-schema";

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
