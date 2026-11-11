import { create } from "zustand";
import { ApiError } from "@/api/client";
import { fetchSession, StreamError, streamChat } from "./api";
import { describeError, TIMEOUT_MESSAGE } from "./copy";
import type { Citation, Retrieved, ToolCall } from "./types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  toolCalls: ToolCall[];
  retrieved: Retrieved[];
  latencyMs: number | null;
  status: "streaming" | "done" | "error" | "stopped";
  error?: string;
}

interface AssistantState {
  sessionId: string | null;
  messages: ChatMessage[];
  streaming: boolean;
  loadingHistory: boolean;
  send: (text: string) => Promise<void>;
  retry: () => Promise<void>;
  stop: () => void;
  reset: () => void;
  hydrate: () => Promise<void>;
}

export const SESSION_KEY = "praca-assistant-session";
export const chatConfig = { stallMs: 45_000 };

function readSession(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function writeSession(id: string | null) {
  try {
    if (id) localStorage.setItem(SESSION_KEY, id);
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable */
  }
}

let counter = 0;
const nextId = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`;

let current: AbortController | null = null;
let userStopped = false;

const blank = (role: ChatMessage["role"], content: string): ChatMessage => ({
  id: nextId(),
  role,
  content,
  citations: [],
  toolCalls: [],
  retrieved: [],
  latencyMs: null,
  status: role === "user" ? "done" : "streaming",
});

export const useAssistant = create<AssistantState>((set, get) => {
  const patch = (
    id: string,
    change: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>),
  ) =>
    set((s) => ({
      messages: s.messages.map((m) =>
        m.id === id ? { ...m, ...(typeof change === "function" ? change(m) : change) } : m,
      ),
    }));

  async function run(question: string, allowFreshSession = true): Promise<void> {
    const reply = blank("assistant", "");
    const controller = new AbortController();
    current = controller;
    userStopped = false;
    set((s) => ({ messages: [...s.messages, reply], streaming: true }));

    let timedOut = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, chatConfig.stallMs);
    };

    let finished = false;
    try {
      arm();
      for await (const event of streamChat(
        { sessionId: get().sessionId, message: question },
        controller.signal,
      )) {
        arm();
        if (event.type === "tool_call") {
          patch(reply.id, (m) => ({ toolCalls: [...m.toolCalls, event.call] }));
        } else if (event.type === "token") {
          patch(reply.id, (m) => ({ content: m.content + event.text }));
        } else if (event.type === "error") {
          throw new StreamError(event.detail, "server");
        } else {
          finished = true;
          const r = event.result;
          writeSession(r.session_id);
          set({ sessionId: r.session_id });
          patch(reply.id, {
            content: r.answer,
            citations: r.citations,
            toolCalls: r.tool_calls,
            retrieved: r.retrieved,
            latencyMs: r.latency_ms,
            status: "done",
          });
        }
      }
      if (!finished) throw new StreamError("A conexão caiu antes do fim da resposta.", "malformed");
    } catch (err) {
      if (timedOut) {
        patch(reply.id, { status: "error", error: TIMEOUT_MESSAGE });
      } else if (userStopped) {
        patch(reply.id, { status: "stopped" });
      } else if (
        err instanceof ApiError &&
        err.status === 404 &&
        get().sessionId &&
        allowFreshSession
      ) {
        clearTimeout(timer);
        writeSession(null);
        set((s) => ({ sessionId: null, messages: s.messages.filter((m) => m.id !== reply.id) }));
        return run(question, false);
      } else {
        patch(reply.id, { status: "error", error: describeError(err) });
      }
    } finally {
      clearTimeout(timer);
      if (current === controller) {
        current = null;
        set({ streaming: false });
      }
    }
  }

  return {
    sessionId: readSession(),
    messages: [],
    streaming: false,
    loadingHistory: false,

    async send(text) {
      const message = text.trim();
      if (!message || get().streaming) return;
      set((s) => ({ messages: [...s.messages, blank("user", message)] }));
      await run(message);
    },

    async retry() {
      if (get().streaming) return;
      const { messages } = get();
      const last = messages[messages.length - 1];
      const question = [...messages].reverse().find((m) => m.role === "user")?.content;
      if (!question || last?.role !== "assistant") return;
      set({ messages: messages.slice(0, -1) });
      await run(question);
    },

    stop() {
      if (!current) return;
      userStopped = true;
      current.abort();
    },

    reset() {
      userStopped = true;
      current?.abort();
      current = null;
      writeSession(null);
      set({ sessionId: null, messages: [], streaming: false, loadingHistory: false });
    },

    async hydrate() {
      const { sessionId, messages, loadingHistory, streaming } = get();
      if (!sessionId || messages.length > 0 || loadingHistory || streaming) return;
      set({ loadingHistory: true });
      try {
        const session = await fetchSession(sessionId);
        if (get().sessionId !== sessionId || get().messages.length > 0) return;
        set({
          messages: session.messages
            .filter((m) => m.role === "user" || m.role === "assistant")
            .map((m) => ({
              ...blank(m.role === "user" ? "user" : "assistant", m.content),
              citations: m.citations,
              toolCalls: m.tool_calls,
              status: "done" as const,
            })),
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) {
          writeSession(null);
          set({ sessionId: null });
        }
      } finally {
        set({ loadingHistory: false });
      }
    },
  };
});

export const useAssistantChat = useAssistant;
