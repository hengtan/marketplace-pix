import { delay, HttpResponse, http } from "msw";
import type { Product } from "@/api/schemas";
import { env } from "@/lib/env";
import { formatMoney } from "@/lib/format";
import { PRODUCTS } from "./data";
import * as db from "./db";

const base = env.apiUrl.replace(/\/$/, "");
const url = (path: string) => `${base}${path}`;

const STORAGE_KEY = "praca-mock-assistant";
const TICK = import.meta.env.MODE === "test" ? 0 : 55;
const SLOW_TICK = import.meta.env.MODE === "test" ? 0 : 450;

interface Citation {
  product_id: string;
  slug: string;
  name: string;
  score: number;
}

interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result_summary: string;
  duration_ms: number;
}

interface Retrieved {
  chunk_id: string;
  product_id: string;
  slug: string;
  name: string;
  category: string;
  price_cents: number;
  content: string;
  score: number;
  source: string;
}

interface Reply {
  answer: string;
  citations: Citation[];
  tool_calls: ToolCall[];
  retrieved: Retrieved[];
}

interface StoredMessage {
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations: Citation[];
  tool_calls: ToolCall[];
}

type Sessions = Record<string, StoredMessage[]>;

function load(): Sessions {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Sessions;
  } catch {
    return {};
  }
}

function save(sessions: Sessions) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  } catch {
    /* storage unavailable */
  }
}

export function resetAssistantMock() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable */
  }
}

const norm = (s: string) =>
  s
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();

const STOP = new Set(
  "quero um uma uns com sem de do da dos das o a os as que qual quais tem ter para pra por em e ou ate r reais real me mostre mostra preciso procuro esse essa isso este esta ha ve voce".split(
    " ",
  ),
);

const CATEGORY_WORDS: Record<string, string> = {
  esporte: "esporte",
  esportes: "esporte",
  casa: "casa",
  tecnologia: "tecnologia",
};

const UUID = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/i;

function stem(word: string) {
  return word.length > 3 ? word.replace(/(es|s)$/, "") : word;
}

function priceCeiling(text: string): number | null {
  const m = /(?:ate|menos de|no maximo)\s*(?:r\$)?\s*(\d+(?:[.,]\d+)?)/.exec(text);
  if (!m?.[1]) return null;
  return Math.round(Number(m[1].replace(",", ".")) * 100);
}

function score(product: Product, words: string[], category: string | null): number {
  const haystack = norm(
    `${product.name} ${product.tags.join(" ")} ${product.description} ${product.category}`,
  );
  let total = category && product.category === category ? 1 : 0;
  for (const w of words) if (haystack.includes(w)) total += norm(product.name).includes(w) ? 2 : 1;
  return total;
}

function chunk(product: Product, rank: number, top: number): Retrieved {
  const relative = top > 0 ? rank / top : 0;
  return {
    chunk_id: `${product.id}:0`,
    product_id: product.id,
    slug: product.slug,
    name: product.name,
    category: product.category,
    price_cents: product.price_cents,
    content: `Produto: ${product.name} | Categoria: ${product.category}\n${product.description} Preço: ${formatMoney(product.price_cents)}. Avaliação: ${product.rating} de 5 em ${product.reviews_count} avaliações. Vendido por ${product.merchant.name}.`,
    score: Number((0.18 + 0.28 * relative).toFixed(4)),
    source: "rerank",
  };
}

const cite = (p: Product, s: number): Citation => ({
  product_id: p.id,
  slug: p.slug,
  name: p.name,
  score: Number(s.toFixed(4)),
});

const OUT_OF_SCOPE =
  "Só consigo ajudar com produtos do catálogo, estoque, pedidos e políticas da loja. Pergunte, por exemplo, por um produto, uma faixa de preço ou o status de um pedido.";

const NOT_FOUND =
  "Não encontrei no catálogo nada que corresponda a isso. Tente descrever o tipo de produto, a categoria ou uma faixa de preço.";

export function composeReply(message: string, history: StoredMessage[]): Reply {
  const text = norm(message);

  const orderId = UUID.exec(message)?.[0];
  if (orderId) {
    const order = db.getOrder(orderId);
    const short = orderId.slice(0, 8);
    const label = { PAID: "pago", PENDING: "aguardando o pagamento", CANCELLED: "cancelado" };
    const summary = order
      ? `Pedido ${short}: ${order.status}, ${formatMoney(order.total_cents)}.`
      : "Não encontrei nenhum pedido com esse código.";
    return {
      answer: order
        ? `O pedido ${short} está ${label[order.status]}, no valor de **${formatMoney(order.total_cents)}**.`
        : "Não encontrei nenhum pedido com esse código. Confira o número na página do pedido.",
      citations: [],
      retrieved: [],
      tool_calls: [
        {
          name: "get_order_status",
          arguments: { order_id: orderId },
          result_summary: summary,
          duration_ms: 12,
        },
      ],
    };
  }

  if (/\bpedido/.test(text)) {
    return {
      answer:
        "Para consultar um pedido, envie o código dele. Você encontra o código completo na página do pedido.",
      citations: [],
      retrieved: [],
      tool_calls: [],
    };
  }

  if (/estoque|disponivel|disponibilidade/.test(text)) {
    const named = PRODUCTS.filter((p) => text.includes(norm(p.name).split(" ")[0] ?? "~~"));
    const previous = [...history].reverse().find((m) => m.citations.length > 0)?.citations ?? [];
    const targets = (
      named.length > 0
        ? named
        : previous.slice(0, 1).flatMap((c) => PRODUCTS.filter((p) => p.id === c.product_id))
    ).slice(0, 2);
    if (targets.length === 0) {
      return {
        answer: NOT_FOUND,
        citations: [],
        retrieved: [],
        tool_calls: [
          {
            name: "search_products",
            arguments: { query: message },
            result_summary: "Nenhum produto encontrado.",
            duration_ms: 4,
          },
        ],
      };
    }
    const calls: ToolCall[] = [];
    const lines: string[] = [];
    targets.forEach((p, i) => {
      const { available } = db.getStock(p.id);
      calls.push({
        name: "get_stock",
        arguments: { product_id: p.id, name: p.name },
        result_summary: `${p.name}: ${available} unidades disponíveis.`,
        duration_ms: 9 + i,
      });
      lines.push(
        available <= 0
          ? `${p.name} está esgotado no momento [${i + 1}]`
          : available <= 5
            ? `${p.name} tem só ${available} ${available === 1 ? "unidade" : "unidades"} em estoque [${i + 1}]`
            : `${p.name} tem **${available} unidades** disponíveis [${i + 1}]`,
      );
    });
    return {
      answer: targets.length === 1 ? `${lines[0]}.` : lines.map((l) => `- ${l}`).join("\n"),
      citations: targets.map((p, i) => cite(p, 0.9 - i * 0.1)),
      retrieved: [],
      tool_calls: calls,
    };
  }

  const category =
    Object.entries(CATEGORY_WORDS).find(([w]) => text.split(/\W+/).includes(w))?.[1] ?? null;
  const words = text
    .split(/[^a-z0-9]+/)
    .filter((w) => w && !STOP.has(w) && !CATEGORY_WORDS[w] && !/^\d+$/.test(w))
    .map(stem);
  const ceiling = priceCeiling(text);

  const ranked = PRODUCTS.filter((p) => (category ? p.category === category : true))
    .filter((p) => (ceiling ? p.price_cents <= ceiling : true))
    .map((p) => ({ p, s: score(p, words, category) }))
    .filter((r) => r.s > 0 && (words.length > 0 || category !== null || ceiling !== null))
    .sort((a, b) => b.s - a.s || b.p.rating - a.p.rating)
    .slice(0, 3);

  const top = ranked[0]?.s ?? 0;
  const listing = ranked.map(({ p }) => `${p.name} (${formatMoney(p.price_cents)})`).join("; ");
  const call: ToolCall = {
    name: "search_products",
    arguments: { query: message },
    result_summary:
      ranked.length === 0
        ? "Nenhum produto encontrado."
        : `${ranked.length} ${ranked.length === 1 ? "produto encontrado" : "produtos encontrados"}: ${listing}.`,
    duration_ms: 7,
  };
  if (ranked.length === 0) {
    return { answer: OUT_OF_SCOPE, citations: [], retrieved: [], tool_calls: [call] };
  }
  const lines = ranked.map(
    ({ p }, i) =>
      `- **${p.name}** por ${formatMoney(p.price_cents)}, nota ${String(p.rating).replace(",", ".")} de 5 [${i + 1}]`,
  );
  return {
    answer: `Encontrei ${ranked.length} ${ranked.length === 1 ? "opção" : "opções"} no catálogo:\n${lines.join("\n")}`,
    citations: ranked.map(({ p, s }) => cite(p, 0.2 + 0.25 * (s / Math.max(top, 1)))),
    retrieved: ranked.map(({ p, s }) => chunk(p, s, top)),
    tool_calls: [call],
  };
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function record(sessionId: string, history: StoredMessage[], message: string, reply: Reply) {
  const now = new Date().toISOString();
  const sessions = load();
  sessions[sessionId] = [
    ...history,
    { role: "user", content: message, created_at: now, citations: [], tool_calls: [] },
    {
      role: "assistant",
      content: reply.answer,
      created_at: now,
      citations: reply.citations,
      tool_calls: reply.tool_calls,
    },
  ];
  save(sessions);
}

interface ChatBody {
  session_id?: string | null;
  message?: string;
}

function prepare(body: ChatBody) {
  const message = (body.message ?? "").trim();
  if (message.length < 1 || message.length > 1000) {
    return {
      error: HttpResponse.json(
        { detail: "invalid message: length must be between 1 and 1000" },
        { status: 422 },
      ),
    } as const;
  }
  const sessions = load();
  if (body.session_id && !sessions[body.session_id]) {
    return { error: HttpResponse.json({ detail: "session not found" }, { status: 404 }) } as const;
  }
  const sessionId = body.session_id ?? crypto.randomUUID();
  const history = sessions[sessionId] ?? [];
  return { message, sessionId, history, reply: composeReply(message, history) } as const;
}

export const assistantHandlers = [
  http.post(url("/api/assistant/chat"), async ({ request }) => {
    const prepared = prepare((await request.json()) as ChatBody);
    if ("error" in prepared) return prepared.error;
    await delay(250);
    const { message, sessionId, history, reply } = prepared;
    record(sessionId, history, message, reply);
    return HttpResponse.json({ session_id: sessionId, ...reply, latency_ms: 240 });
  }),

  http.post(url("/api/assistant/chat/stream"), async ({ request }) => {
    const prepared = prepare((await request.json()) as ChatBody);
    if ("error" in prepared) return prepared.error;
    const { message, sessionId, history, reply } = prepared;
    const failing = /simular erro/i.test(message);
    const slow = /resposta lenta/i.test(message);
    const encoder = new TextEncoder();
    let cancelled = false;

    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const emit = async (event: string, data: unknown, wait = TICK) => {
          if (cancelled) return;
          const raw = sse(event, data);
          const cut = Math.floor(raw.length / 2);
          controller.enqueue(encoder.encode(raw.slice(0, cut)));
          await sleep(1);
          if (cancelled) return;
          controller.enqueue(encoder.encode(raw.slice(cut)));
          await sleep(wait);
        };
        const started = Date.now();
        await sleep(slow ? SLOW_TICK : TICK * 4);
        for (const call of reply.tool_calls) await emit("tool_call", call, TICK * 6);
        if (failing) {
          await emit("error", { detail: "model unavailable" });
          if (!cancelled) controller.close();
          return;
        }
        for (const piece of reply.answer.split(/(?<=\s)/)) {
          await emit("token", { text: piece }, slow ? SLOW_TICK : TICK);
        }
        record(sessionId, history, message, reply);
        await emit("done", {
          session_id: sessionId,
          ...reply,
          latency_ms: Math.max(1, Date.now() - started),
        });
        if (!cancelled) controller.close();
      },
      cancel() {
        cancelled = true;
      },
    });

    return new HttpResponse(stream, {
      headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" },
    });
  }),

  http.get(url("/api/assistant/sessions/:id"), async ({ params }) => {
    await delay(150);
    const messages = load()[String(params.id)];
    if (!messages) return HttpResponse.json({ detail: "session not found" }, { status: 404 });
    return HttpResponse.json({
      session_id: params.id,
      created_at: messages[0]?.created_at ?? new Date().toISOString(),
      messages,
    });
  }),
];
