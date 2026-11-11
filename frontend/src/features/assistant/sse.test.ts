import { describe, expect, it } from "vitest";
import { parseAssistantEvent, StreamError } from "./api";
import { readSse, type SseMessage, SseParser } from "./sse";

function parse(chunks: string[]): SseMessage[] {
  const out: SseMessage[] = [];
  const parser = new SseParser((m) => out.push(m));
  for (const c of chunks) parser.feed(c);
  parser.end();
  return out;
}

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const out: SseMessage[] = [];
  for await (const m of readSse(stream)) out.push(m);
  return out;
}

describe("SseParser", () => {
  it("parses complete events", () => {
    const events = parse(['event: token\ndata: {"text":"Oi"}\n\nevent: done\ndata: {}\n\n']);
    expect(events).toEqual([
      { event: "token", data: '{"text":"Oi"}' },
      { event: "done", data: "{}" },
    ]);
  });

  it("joins an event broken in the middle of a line", () => {
    const events = parse(["eve", "nt: tok", "en\nda", 'ta: {"text":"ol', 'á"}\n', "\n"]);
    expect(events).toEqual([{ event: "token", data: '{"text":"olá"}' }]);
  });

  it("joins an event broken between the blank-line separators", () => {
    const events = parse(["event: token\ndata: 1\n", "\nevent: token\ndata: 2\n\n"]);
    expect(events.map((e) => e.data)).toEqual(["1", "2"]);
  });

  it("handles CRLF and a CR at a chunk boundary", () => {
    const events = parse([
      "event: token\r\ndata: a\r\n\r\n",
      "event: token\r",
      "\ndata: b\r",
      "\n\r",
      "\n",
    ]);
    expect(events.map((e) => e.data)).toEqual(["a", "b"]);
  });

  it("ignores comments, blank runs and unknown fields", () => {
    const events = parse([
      ": keep-alive\n\n\n\nid: 7\nretry: 100\nevent: token\n: note\ndata: x\n\n",
    ]);
    expect(events).toEqual([{ event: "token", data: "x" }]);
  });

  it("joins multi-line data with a newline", () => {
    expect(parse(["data: a\ndata: b\n\n"])).toEqual([{ event: "message", data: "a\nb" }]);
  });

  it("flushes a last event that has no closing blank line", () => {
    expect(parse(['event: done\ndata: {"ok":true}'])).toEqual([
      { event: "done", data: '{"ok":true}' },
    ]);
  });
});

describe("readSse", () => {
  it("decodes multi-byte characters split across chunks", async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"text":"ção"}\n\n');
    const cut = bytes.indexOf(0xc3) + 1;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, cut));
        controller.enqueue(bytes.slice(cut));
        controller.close();
      },
    });
    const [message] = await collect(stream);
    expect(parseAssistantEvent(message as SseMessage)).toEqual({ type: "token", text: "ção" });
  });

  it("supports done without any token", async () => {
    const done = {
      session_id: "s1",
      answer: "Pronto.",
      citations: [],
      tool_calls: [],
      retrieved: [],
      latency_ms: 12,
    };
    const messages = await collect(streamOf([`event: done\ndata: ${JSON.stringify(done)}\n\n`]));
    const events = messages.map(parseAssistantEvent);
    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      type: "done",
      result: { answer: "Pronto.", session_id: "s1" },
    });
  });
});

describe("parseAssistantEvent", () => {
  it("maps tool_call", () => {
    const event = parseAssistantEvent({
      event: "tool_call",
      data: JSON.stringify({
        name: "get_stock",
        arguments: { product_id: "p" },
        result_summary: "ok",
        duration_ms: 4,
      }),
    });
    expect(event).toEqual({
      type: "tool_call",
      call: {
        name: "get_stock",
        arguments: { product_id: "p" },
        result_summary: "ok",
        duration_ms: 4,
      },
    });
  });

  it("maps the error event", () => {
    expect(parseAssistantEvent({ event: "error", data: '{"detail":"model unavailable"}' })).toEqual(
      {
        type: "error",
        detail: "model unavailable",
      },
    );
  });

  it("maps the budget error with its scope, limit and wait", () => {
    expect(
      parseAssistantEvent({
        event: "error",
        data: '{"detail":"budget exceeded","scope":"user","limit":"tokens","retry_after_seconds":600}',
      }),
    ).toEqual({
      type: "error",
      detail: "budget exceeded",
      scope: "user",
      limit: "tokens",
      retryAfter: 600,
    });
  });

  it("maps the degraded warning", () => {
    expect(
      parseAssistantEvent({
        event: "warning",
        data: '{"detail":"model unavailable","reason":"llm_timeout"}',
      }),
    ).toEqual({ type: "warning", detail: "model unavailable", reason: "llm_timeout" });
  });

  it("keeps degraded and warning from a done event", () => {
    const event = parseAssistantEvent({
      event: "done",
      data: JSON.stringify({
        session_id: "s1",
        answer: "ok",
        degraded: true,
        warning: "model unavailable",
        cached: false,
      }),
    });
    expect(event).toMatchObject({
      type: "done",
      result: { degraded: true, warning: "model unavailable", cached: false },
    });
  });

  it("skips unknown events and malformed tokens", () => {
    expect(parseAssistantEvent({ event: "ping", data: "{}" })).toBeNull();
    expect(parseAssistantEvent({ event: "token", data: "{broken" })).toBeNull();
  });

  it("rejects a malformed done event", () => {
    expect(() => parseAssistantEvent({ event: "done", data: "{}" })).toThrow(StreamError);
  });
});
