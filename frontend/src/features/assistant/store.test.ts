import { delay, HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { chatConfig, SESSION_KEY, useAssistant } from "./store";

const api = (path: string) => `${env.apiUrl.replace(/\/$/, "")}/api/assistant${path}`;
const state = () => useAssistant.getState();
const assistantReply = () =>
  state()
    .messages.filter((m) => m.role === "assistant")
    .at(-1);

function sseStream(parts: (string | Promise<void>)[], onCancel?: () => void) {
  const encoder = new TextEncoder();
  return new HttpResponse(
    new ReadableStream<Uint8Array>({
      async start(controller) {
        for (const part of parts) {
          if (typeof part === "string") controller.enqueue(encoder.encode(part));
          else await part;
        }
        controller.close();
      },
      cancel: onCancel,
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  );
}

const done = (answer: string, extra: object = {}) =>
  `event: done\ndata: ${JSON.stringify({
    session_id: "11111111-1111-4111-8111-111111111111",
    answer,
    citations: [],
    tool_calls: [],
    retrieved: [],
    latency_ms: 20,
    ...extra,
  })}\n\n`;

beforeEach(() => {
  chatConfig.stallMs = 45_000;
  state().reset();
});

describe("assistant chat store", () => {
  it("streams tokens and finishes with the final payload and session", async () => {
    await state().send("quero um fone com cancelamento de ruído");
    const reply = assistantReply();
    expect(reply?.status).toBe("done");
    expect(reply?.content).toContain("Fone Bluetooth Nova ANC");
    expect(reply?.citations.length).toBeGreaterThan(0);
    expect(reply?.toolCalls[0]?.name).toBe("search_products");
    expect(reply?.retrieved.length).toBeGreaterThan(0);
    expect(reply?.latencyMs).toBeGreaterThan(0);
    expect(state().sessionId).toBeTruthy();
    expect(localStorage.getItem(SESSION_KEY)).toBe(state().sessionId);
    expect(state().streaming).toBe(false);
  });

  it("shows partial text and tool calls while streaming", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => {
      release = r;
    });
    server.use(
      http.post(api("/chat/stream"), () =>
        sseStream([
          'event: tool_call\ndata: {"name":"get_stock","arguments":{},"result_summary":"ok","duration_ms":3}\n\n',
          'event: token\ndata: {"text":"Tem "}\n\n',
          gate,
          done("Tem estoque."),
        ]),
      ),
    );
    const pending = state().send("esse tem estoque?");
    await expect.poll(() => assistantReply()?.content).toBe("Tem ");
    expect(assistantReply()?.status).toBe("streaming");
    expect(assistantReply()?.toolCalls).toHaveLength(1);
    expect(state().streaming).toBe(true);
    release();
    await pending;
    expect(assistantReply()?.content).toBe("Tem estoque.");
    expect(assistantReply()?.status).toBe("done");
  });

  it("stops generation and keeps the partial answer", async () => {
    let cancelled = false;
    server.use(
      http.post(api("/chat/stream"), () =>
        sseStream(
          ['event: token\ndata: {"text":"Parcial "}\n\n', new Promise<void>(() => {})],
          () => {
            cancelled = true;
          },
        ),
      ),
    );
    const pending = state().send("pergunta longa");
    await expect.poll(() => assistantReply()?.content).toBe("Parcial ");
    state().stop();
    await pending;
    expect(assistantReply()?.status).toBe("stopped");
    expect(assistantReply()?.content).toBe("Parcial ");
    expect(state().streaming).toBe(false);
    await expect.poll(() => cancelled).toBe(true);
  });

  it("reports a server error and retries the same question", async () => {
    server.use(
      http.post(api("/chat/stream"), () => HttpResponse.json({ detail: "x" }, { status: 502 })),
    );
    await state().send("quero um fone");
    expect(assistantReply()?.status).toBe("error");
    expect(assistantReply()?.error).toMatch(/indisponível/);

    server.resetHandlers();
    await state().retry();
    expect(state().messages.filter((m) => m.role === "user")).toHaveLength(1);
    expect(assistantReply()?.status).toBe("done");
    expect(assistantReply()?.content).toContain("Fone Bluetooth Nova ANC");
  });

  it("surfaces the error event emitted inside the stream", async () => {
    await state().send("simular erro");
    expect(assistantReply()?.status).toBe("error");
    expect(assistantReply()?.error).toMatch(/indisponível/);
  });

  it("reports a network failure", async () => {
    server.use(http.post(api("/chat/stream"), () => HttpResponse.error()));
    await state().send("oi");
    expect(assistantReply()?.error).toMatch(/Sem conexão/);
  });

  it("fails clearly when the stream ends without a done event", async () => {
    server.use(
      http.post(api("/chat/stream"), () => sseStream(['event: token\ndata: {"text":"Meio"}\n\n'])),
    );
    await state().send("oi");
    expect(assistantReply()?.status).toBe("error");
    expect(assistantReply()?.content).toBe("Meio");
  });

  it("times out when the stream goes silent", async () => {
    chatConfig.stallMs = 60;
    server.use(http.post(api("/chat/stream"), () => sseStream([new Promise<void>(() => {})])));
    await state().send("oi");
    expect(assistantReply()?.status).toBe("error");
    expect(assistantReply()?.error).toMatch(/demorou demais/);
    expect(state().streaming).toBe(false);
  });

  it("starts a fresh session when the stored one is unknown", async () => {
    await state().send("quero um fone");
    const first = state().sessionId;
    expect(first).toBeTruthy();
    localStorage.setItem("praca-mock-assistant", "{}");
    await state().send("e uma caixa de som?");
    expect(assistantReply()?.status).toBe("done");
    expect(state().sessionId).not.toBe(first);
  });

  it("keeps conversation memory through the session", async () => {
    await state().send("quero um fone com cancelamento de ruído");
    await state().send("esse tem estoque?");
    expect(assistantReply()?.toolCalls[0]?.name).toBe("get_stock");
    expect(assistantReply()?.content).toMatch(/Fone Bluetooth Nova ANC/);
  });

  it("hydrates history from the session and drops unknown ones", async () => {
    await state().send("quero um fone com cancelamento de ruído");
    const id = state().sessionId;
    useAssistant.setState({ messages: [], sessionId: id });
    await state().hydrate();
    expect(state().messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(state().messages[1]?.citations.length).toBeGreaterThan(0);

    useAssistant.setState({ messages: [], sessionId: "00000000-0000-4000-8000-000000000000" });
    await state().hydrate();
    expect(state().sessionId).toBeNull();
  });

  it("clears everything on a new conversation", async () => {
    await state().send("quero um fone");
    state().reset();
    expect(state().messages).toEqual([]);
    expect(state().sessionId).toBeNull();
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it("ignores a second send while streaming", async () => {
    server.use(
      http.post(api("/chat/stream"), async () => {
        await delay(30);
        return sseStream([done("ok")]);
      }),
    );
    const first = state().send("um");
    await state().send("dois");
    await first;
    expect(state().messages.filter((m) => m.role === "user")).toHaveLength(1);
  });
});
