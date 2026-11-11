import type { z } from "zod";
import { env } from "@/lib/env";
import { useAuth } from "@/store/auth";
import { errorSchema, refreshResponseSchema } from "./schemas";

export class ApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type Query = Record<string, string | number | undefined | null>;

interface RequestOptions<S extends z.ZodType> {
  schema: S;
  query?: Query;
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  auth?: boolean;
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
  try {
    const parsed = errorSchema.safeParse(await res.json());
    if (parsed.success && typeof parsed.data.detail === "string") message = parsed.data.detail;
  } catch {
    /* body is not JSON */
  }
  return new ApiError(message, res.status);
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

async function send(path: string, opts: RequestOptions<z.ZodType>, token: string | null) {
  const { query, method = "GET", body, headers, signal } = opts;
  return fetch(buildUrl(path, query), {
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

export async function request<S extends z.ZodType>(
  path: string,
  opts: RequestOptions<S>,
): Promise<z.infer<S>> {
  const useToken = opts.auth !== false;
  let res: Response;
  try {
    res = await send(path, opts, useToken ? useAuth.getState().accessToken : null);
    if (res.status === 401 && useToken && useAuth.getState().refreshToken) {
      if (await refreshOnce()) res = await send(path, opts, useAuth.getState().accessToken);
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
  const res = await fetch(buildUrl(path));
  if (!res.ok) throw await toError(res);
  return res.text();
}
