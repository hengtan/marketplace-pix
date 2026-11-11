export interface SseMessage {
  event: string;
  data: string;
}

export class SseParser {
  private buffer = "";
  private event = "";
  private data: string[] = [];
  private hasData = false;
  private skipLf = false;

  constructor(private readonly onMessage: (message: SseMessage) => void) {}

  feed(chunk: string): void {
    let text = chunk;
    if (this.skipLf && text.startsWith("\n")) text = text.slice(1);
    this.skipLf = false;
    this.buffer += text;

    let start = 0;
    for (let i = 0; i < this.buffer.length; i++) {
      const ch = this.buffer[i];
      if (ch !== "\n" && ch !== "\r") continue;
      this.line(this.buffer.slice(start, i));
      if (ch === "\r") {
        if (this.buffer[i + 1] === "\n") i++;
        else if (i + 1 === this.buffer.length) this.skipLf = true;
      }
      start = i + 1;
    }
    this.buffer = this.buffer.slice(start);
  }

  end(): void {
    if (this.buffer) {
      this.line(this.buffer);
      this.buffer = "";
    }
    this.dispatch();
  }

  private line(line: string): void {
    if (line === "") {
      this.dispatch();
      return;
    }
    if (line.startsWith(":")) return;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.event = value;
    else if (field === "data") {
      this.data.push(value);
      this.hasData = true;
    }
  }

  private dispatch(): void {
    if (this.hasData) {
      this.onMessage({ event: this.event || "message", data: this.data.join("\n") });
    }
    this.event = "";
    this.data = [];
    this.hasData = false;
  }
}

export async function* readSse(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<SseMessage> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const queue: SseMessage[] = [];
  const parser = new SseParser((m) => queue.push(m));
  const onAbort = () => void reader.cancel().catch(() => {});
  signal?.addEventListener("abort", onAbort);
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.feed(decoder.decode(value, { stream: true }));
      while (queue.length) yield queue.shift() as SseMessage;
    }
    parser.feed(decoder.decode());
    parser.end();
    while (queue.length) yield queue.shift() as SseMessage;
  } finally {
    signal?.removeEventListener("abort", onAbort);
    reader.releaseLock();
  }
}
