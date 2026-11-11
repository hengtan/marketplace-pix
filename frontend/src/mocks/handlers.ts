import { delay, HttpResponse, http } from "msw";
import type { Product } from "@/api/schemas";
import { env } from "@/lib/env";
import { buildCategories, PRODUCTS } from "./data";
import * as db from "./db";

const base = env.apiUrl.replace(/\/$/, "");
const url = (path: string) => `${base}${path}`;

const LATENCY = 120;

function paginate<T>(items: T[], page: number, pageSize: number) {
  const start = (page - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    total: items.length,
    page,
    page_size: pageSize,
  };
}

function normalize(s: string): string {
  return s
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

function relevance(p: Product, q: string): number {
  const n = normalize(p.name);
  if (n.startsWith(q)) return 3;
  if (n.includes(q)) return 2;
  return 1;
}

function notFound(detail: string) {
  return HttpResponse.json({ detail }, { status: 404 });
}

export const handlers = [
  http.get(url("/api/catalog/products/slug/:slug"), async ({ params }) => {
    await delay(LATENCY);
    const p = PRODUCTS.find((x) => x.slug === params.slug);
    return p ? HttpResponse.json(p) : notFound("Produto não encontrado");
  }),

  http.get(url("/api/catalog/products/by-ids"), async ({ request }) => {
    await delay(LATENCY);
    const ids = (new URL(request.url).searchParams.get("ids") ?? "").split(",").filter(Boolean);
    const items = ids
      .map((id) => PRODUCTS.find((p) => p.id === id))
      .filter((p): p is Product => Boolean(p));
    return HttpResponse.json({
      items,
      total: items.length,
      page: 1,
      page_size: Math.max(items.length, 1),
    });
  }),

  http.get(url("/api/catalog/products/:id"), async ({ params }) => {
    await delay(LATENCY);
    const p = PRODUCTS.find((x) => x.id === params.id);
    return p ? HttpResponse.json(p) : notFound("Produto não encontrado");
  }),

  http.get(url("/api/catalog/products"), async ({ request }) => {
    await delay(LATENCY * 2);
    const sp = new URL(request.url).searchParams;
    if (sp.get("q") === "__erro")
      return HttpResponse.json({ detail: "Falha simulada" }, { status: 500 });
    const q = normalize(sp.get("q") ?? "").trim();
    const category = sp.get("category");
    const min = Number(sp.get("min_price_cents") ?? 0);
    const max = Number(sp.get("max_price_cents") ?? Number.POSITIVE_INFINITY);
    const sort = sp.get("sort") ?? "relevance";
    const page = Math.max(1, Number(sp.get("page") ?? 1));
    const pageSize = Math.min(48, Math.max(1, Number(sp.get("page_size") ?? 12)));

    let list = PRODUCTS.filter(
      (p) =>
        (!category || p.category === category) &&
        p.price_cents >= min &&
        p.price_cents <= max &&
        (!q ||
          normalize(`${p.name} ${p.description} ${p.tags.join(" ")} ${p.merchant.name}`).includes(
            q,
          )),
    );
    list = [...list].sort((a, b) => {
      switch (sort) {
        case "price_asc":
          return a.price_cents - b.price_cents;
        case "price_desc":
          return b.price_cents - a.price_cents;
        case "newest":
          return b.created_at.localeCompare(a.created_at);
        case "rating":
          return b.rating - a.rating || b.reviews_count - a.reviews_count;
        default:
          return q
            ? relevance(b, q) - relevance(a, q)
            : b.reviews_count * b.rating - a.reviews_count * a.rating;
      }
    });
    return HttpResponse.json(paginate(list, page, pageSize));
  }),

  http.get(url("/api/catalog/categories"), async () => {
    await delay(LATENCY / 2);
    return HttpResponse.json(buildCategories());
  }),

  http.get(url("/api/inventory/stock"), async ({ request }) => {
    await delay(LATENCY / 2);
    const ids = (new URL(request.url).searchParams.get("product_ids") ?? "")
      .split(",")
      .filter(Boolean);
    return HttpResponse.json(ids.map((id) => db.getStock(id)));
  }),

  http.get(url("/api/inventory/stock/:id"), ({ params }) =>
    HttpResponse.json(db.getStock(String(params.id))),
  ),

  http.put(url("/api/inventory/stock/:id"), async ({ params, request }) => {
    const body = (await request.json()) as { available: number };
    db.setStock(String(params.id), body.available);
    return HttpResponse.json(db.getStock(String(params.id)));
  }),

  http.post(url("/api/orders"), async ({ request }) => {
    await delay(LATENCY * 3);
    const key = request.headers.get("Idempotency-Key");
    if (!key)
      return HttpResponse.json({ detail: "Idempotency-Key é obrigatório" }, { status: 400 });
    const body = (await request.json()) as Parameters<typeof db.createOrder>[0];
    try {
      const { id } = db.createOrder(body, key);
      return HttpResponse.json({ id }, { status: 201 });
    } catch (err) {
      return HttpResponse.json(
        { detail: err instanceof Error ? err.message : "Pedido inválido" },
        { status: 422 },
      );
    }
  }),

  http.get(url("/api/orders/:id"), async ({ params }) => {
    await delay(LATENCY / 2);
    const o = db.getOrder(String(params.id));
    return o ? HttpResponse.json(o) : notFound("Pedido não encontrado");
  }),

  http.get(url("/api/orders"), async ({ request }) => {
    await delay(LATENCY);
    const sp = new URL(request.url).searchParams;
    const list = db.listOrders(sp.get("customer_id") ?? "");
    return HttpResponse.json(
      paginate(list, Math.max(1, Number(sp.get("page") ?? 1)), Number(sp.get("page_size") ?? 20)),
    );
  }),

  http.get(url("/api/payments/by-order/:orderId"), async ({ params }) => {
    await delay(LATENCY / 2);
    const p = db.getPayment(String(params.orderId));
    return p ? HttpResponse.json(p) : notFound("Pagamento ainda não gerado");
  }),

  http.post(url("/api/payments/dev/psp/charges/:chargeId/pay"), async ({ params }) => {
    await delay(LATENCY);
    const ok = db.payCharge(String(params.chargeId));
    return ok
      ? HttpResponse.json({ status: "paid" })
      : HttpResponse.json({ detail: "Cobrança não pode ser paga" }, { status: 409 });
  }),

  http.get(url("/api/ledger/merchants/:id/summary"), async ({ params, request }) => {
    await delay(LATENCY * 2);
    const days = Number(new URL(request.url).searchParams.get("days") ?? 30);
    return HttpResponse.json(db.merchantSummary(String(params.id), days));
  }),

  http.get(url("/api/ledger/accounts/:account/entries"), async ({ params, request }) => {
    await delay(LATENCY);
    const sp = new URL(request.url).searchParams;
    const merchantId = String(params.account).replace("merchant:", "");
    return HttpResponse.json(
      paginate(
        db.merchantEntries(merchantId),
        Math.max(1, Number(sp.get("page") ?? 1)),
        Number(sp.get("page_size") ?? 20),
      ),
    );
  }),

  http.get(url("/api/ledger/reconciliation"), async () => {
    await delay(LATENCY);
    return HttpResponse.json(db.reconciliation());
  }),

  http.get(url("/api/notifications/:id/preview"), ({ params }) => {
    const html = db.notificationHtml(String(params.id));
    return html
      ? new HttpResponse(html, { headers: { "Content-Type": "text/html; charset=utf-8" } })
      : notFound("Notificação não encontrada");
  }),

  http.get(url("/api/notifications"), async ({ request }) => {
    await delay(LATENCY);
    const sp = new URL(request.url).searchParams;
    return HttpResponse.json(
      paginate(
        db.listNotifications(sp.get("customer_id") ?? ""),
        Math.max(1, Number(sp.get("page") ?? 1)),
        Number(sp.get("page_size") ?? 20),
      ),
    );
  }),
];
