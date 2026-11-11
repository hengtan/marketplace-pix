import { ApiError, buildUrl, request, toError } from "@/api/client";
import { readSse, type SseMessage } from "./sse";
import { type AssistantEvent, chatResponseSchema, sessionSchema, toolCallSchema } from "./types";

export class StreamError extends Error {
  constructor(
    message: string,
    readonly kind: "malformed" | "server",
  ) {
    super(message);
    this.name = "StreamError";
  }
}

function parseJson(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return undefined;
  }
}

export function parseAssistantEvent(message: SseMessage): AssistantEvent | null {
  const json = parseJson(message.data);
  switch (message.event) {
    case "token": {
      const text = (json as { text?: unknown } | undefined)?.text;
      return typeof text === "string" ? { type: "token", text } : null;
    }
    case "tool_call": {
      const parsed = toolCallSchema.safeParse(json);
      return parsed.success ? { type: "tool_call", call: parsed.data } : null;
    }
    case "done": {
      const parsed = chatResponseSchema.safeParse(json);
      if (!parsed.success) throw new StreamError("Resposta inesperada do servidor.", "malformed");
      return { type: "done", result: parsed.data };
    }
    case "error": {
      const detail = (json as { detail?: unknown } | undefined)?.detail;
      return { type: "error", detail: typeof detail === "string" ? detail : "" };
    }
    default:
      return null;
  }
}

export async function* streamChat(
  input: { sessionId: string | null; message: string },
  signal: AbortSignal,
): AsyncGenerator<AssistantEvent> {
  let res: Response;
  try {
    res = await fetch(buildUrl("/api/assistant/chat/stream"), {
      method: "POST",
      signal,
      headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
      body: JSON.stringify({
        message: input.message,
        ...(input.sessionId ? { session_id: input.sessionId } : {}),
      }),
    });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new ApiError("Sem conexão com o servidor.", 0);
  }
  if (!res.ok) throw await toError(res);
  if (!res.body) throw new ApiError("Resposta vazia do servidor.", res.status);

  for await (const message of readSse(res.body, signal)) {
    const event = parseAssistantEvent(message);
    if (event) yield event;
  }
}

export function fetchSession(id: string, signal?: AbortSignal) {
  return request(`/api/assistant/sessions/${encodeURIComponent(id)}`, {
    schema: sessionSchema,
    signal,
  });
}
