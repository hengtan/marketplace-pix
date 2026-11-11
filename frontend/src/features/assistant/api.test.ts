import { describe, expect, it } from "vitest";
import { parseAssistantEvent } from "./api";

const base = {
  session_id: "s",
  answer: "ok",
  citations: [],
  tool_calls: [],
  retrieved: [],
  latency_ms: 12,
};

describe("parseAssistantEvent done", () => {
  it("accepts a null warning, which is what the backend sends when nothing went wrong", () => {
    const event = parseAssistantEvent({
      event: "done",
      data: JSON.stringify({ ...base, cached: true, degraded: false, warning: null }),
    });
    expect(event?.type).toBe("done");
  });

  it("keeps a textual warning", () => {
    const event = parseAssistantEvent({
      event: "done",
      data: JSON.stringify({ ...base, degraded: true, warning: "modelo indisponível" }),
    });
    expect(event).toMatchObject({ type: "done", result: { warning: "modelo indisponível" } });
  });
});
