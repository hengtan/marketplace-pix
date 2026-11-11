import type * as z from "zod/mini";
import { env } from "@/lib/env";
import { notifySessionExpired } from "@/lib/session";
import { useAuth, whenRestored } from "@/store/auth";
import { errorSchema, refreshResponseSchema } from "./schemas";

export interface ApiErrorInfo {
  retryAfter?: number;
  scope?: string;
  limit?: string;
  code?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly retryAfter?: number;
  readonly scope?: string;
  readonly limit?: string;
  readonly code?: string;
  constructor(message: string, status: number, info: ApiErrorInfo = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfter = info.retryAfter;
    this.scope = info.scope;
    this.limit = info.limit;
    this.code = info.code;
  }
}

export function parseRetryAfter(value: string | null | undefined): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.ceil(seconds);
  const date = Date.parse(value);
  if (Number.isNaN(date)) return undefined;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

type Query = Record<string, string | number | undefined | null>;

interface RequestOptions<S extends z.ZodMiniType> {
  schema: S;
  query?: Query;
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  auth?: boolean;
  waitForRestore?: boolean;
}

export function buildUrl(path: string, query?: Query): string {
  const base = env.apiUrl.replace(/\/$/, "");
  const url = new URL(`${base}${path}`, window.location.origin);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

export async function toError(res: Response): Promise<ApiError> {
  let message = "Algo deu errado. Tente novamente em instantes.";
  let info: ApiErrorInfo = { retryAfter: parseRetryAfter(res.headers.get("Retry-After")) };
  try {
    const body: unknown = await res.json();
    const parsed = errorSchema.safeParse(body);
    if (parsed.success && typeof parsed.data.detail === "string") message = parsed.data.detail;
    if (body && typeof body === "object") {
      const extra = body as Record<string, unknown>;
      info = {
        retryAfter:
          info.retryAfter ??
          (typeof extra.retry_after_seconds === "number" ? extra.retry_after_seconds : undefined),
        scope: typeof extra.scope === "string" ? extra.scope : undefined,
        limit: typeof extra.limit === "string" ? extra.limit : undefined,
        code: typeof extra.code === "string" ? extra.code : undefined,
      };
    }
  } catch {
    /* body is not JSON */
  }
  return new ApiError(message, res.status, info);
}

let refreshing: Promise<boolean> | null = null;

async function refreshSession(): Promise<boolean> {
  const { refreshToken, setTokens, clear } = useAuth.getState();
  if (!refreshToken) return false;
  try {
    const res = await fetch(buildUrl("/api/auth/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) {
      clear();
      return false;
    }
    const parsed = refreshResponseSchema.safeParse(await res.json());
    if (!parsed.success) return false;
    setTokens(parsed.data.access_token, parsed.data.refresh_token, parsed.data.expires_in);
    return true;
  } catch {
    return false;
  }
}

export function refreshOnce(): Promise<boolean> {
  refreshing ??= refreshSession().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

declare global {
  interface Window {
    __early?: Record<string, Promise<Response | undefined> | undefined>;
  }
}

async function takeEarly(url: string): Promise<Response | undefined> {
  const pending = window.__early?.[url];
  if (!pending || !window.__early) return undefined;
  delete window.__early[url];
  const res = await pending;
  return res?.ok ? res : undefined;
}

async function send(path: string, opts: RequestOptions<z.ZodMiniType>, token: string | null) {
  const { query, method = "GET", body, headers, signal } = opts;
  const url = buildUrl(path, query);
  if (method === "GET" && !token) {
    const early = await takeEarly(url);
    if (early) return early;
  }
  return fetch(url, {
    method,
    signal,
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

export async function authedFetch(
  url: string,
  init: RequestInit & { headers?: Record<string, string> } = {},
): Promise<Response> {
  await whenRestored();
  const attempt = (token: string | null) =>
    fetch(url, {
      ...init,
      headers: { ...init.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
  const signedIn = Boolean(useAuth.getState().accessToken);
  let res = await attempt(useAuth.getState().accessToken);
  if (res.status === 401 && signedIn) {
    if (useAuth.getState().refreshToken && (await refreshOnce())) {
      res = await attempt(useAuth.getState().accessToken);
    } else {
      useAuth.getState().clear();
    }
    if (res.status === 401) {
      useAuth.getState().clear();
      notifySessionExpired();
    }
  }
  return res;
}

export async function request<S extends z.ZodMiniType>(
  path: string,
  opts: RequestOptions<S>,
): Promise<z.infer<S>> {
  const useToken = opts.auth !== false;
  let res: Response;
  try {
    if (useToken && opts.waitForRestore !== false) await whenRestored();
    const signedIn = Boolean(useAuth.getState().accessToken);
    res = await send(path, opts, useToken ? useAuth.getState().accessToken : null);
    if (res.status === 401 && useToken && signedIn) {
      if (useAuth.getState().refreshToken && (await refreshOnce())) {
        res = await send(path, opts, useAuth.getState().accessToken);
      } else {
        useAuth.getState().clear();
      }
      if (res.status === 401) {
        useAuth.getState().clear();
        notifySessionExpired();
      }
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("Sem conexão com o servidor. Confira sua internet e tente de novo.", 0);
  }
  if (!res.ok) throw await toError(res);
  const json: unknown = res.status === 204 ? null : await res.json();
  const parsed = opts.schema.safeParse(json);
  if (!parsed.success) {
    throw new ApiError("Resposta inesperada do servidor.", res.status);
  }
  return parsed.data;
}

export async function fetchText(path: string): Promise<string> {
  const res = await authedFetch(buildUrl(path));
  if (!res.ok) throw await toError(res);
  return res.text();
}
