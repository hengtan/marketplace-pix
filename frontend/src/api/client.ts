import type { z } from "zod";
import { env } from "@/lib/env";
import { errorSchema } from "./schemas";

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

async function toError(res: Response): Promise<ApiError> {
  let message = "Algo deu errado. Tente novamente em instantes.";
  try {
    const parsed = errorSchema.safeParse(await res.json());
    if (parsed.success && typeof parsed.data.detail === "string") message = parsed.data.detail;
  } catch {
    /* body is not JSON */
  }
  return new ApiError(message, res.status);
}

export async function request<S extends z.ZodType>(
  path: string,
  { schema, query, method = "GET", body, headers, signal }: RequestOptions<S>,
): Promise<z.infer<S>> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), {
      method,
      signal,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("Sem conexão com o servidor. Confira sua internet e tente de novo.", 0);
  }
  if (!res.ok) throw await toError(res);
  const json: unknown = res.status === 204 ? null : await res.json();
  const parsed = schema.safeParse(json);
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
