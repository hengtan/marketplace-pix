import { delay, HttpResponse, http } from "msw";
import type { Product } from "@/api/schemas";
import { env } from "@/lib/env";
import { assistantHandlers } from "./assistant";
import { authHandlers, bearer, type MockAccount } from "./auth";
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

const pendingCharges = new Set<string>();

const forbidden = () => HttpResponse.json({ detail: "forbidden" }, { status: 403 });
const unauthorized = () => HttpResponse.json({ detail: "not authenticated" }, { status: 401 });

function writeScope(account: MockAccount): { merchantId: string | null } | null {
  if (account.readOnly) return null;
  if (account.roles.includes("admin")) return { merchantId: null };
  if (account.roles.includes("merchant") && account.merchant_id)
    return { merchantId: account.merchant_id };
  return null;
}

function canSeeReserved(account: MockAccount | null, productId: string): boolean {
  if (!account) return false;
  if (account.roles.includes("admin")) return true;
  if (!account.roles.includes("merchant") || !account.merchant_id) return false;
  return db.canWriteProduct(productId, account.merchant_id);
}

const stockFor =
  (account: MockAccount | null) =>
  ({
    product_id,
    available,
    reserved,
  }: {
    product_id: string;
    available: number;
    reserved: number;
  }) =>
    canSeeReserved(account, product_id)
      ? { product_id, available, reserved }
      : { product_id, available };

export const handlers = [
  ...assistantHandlers,
  ...authHandlers,

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

  http.get(url("/api/inventory/stock/mine"), async ({ request }) => {
    await delay(LATENCY / 2);
    const account = bearer(request);
    if (!account) return unauthorized();
    const scope = writeScope(account);
    if (!scope?.merchantId) return forbidden();
    return HttpResponse.json(db.merchantStock(scope.merchantId));
  }),

  http.get(url("/api/inventory/stock"), async ({ request }) => {
    await delay(LATENCY / 2);
    const account = bearer(request);
    const ids = (new URL(request.url).searchParams.get("product_ids") ?? "")
      .split(",")
      .filter(Boolean);
    return HttpResponse.json(ids.map((id) => stockFor(account)(db.getStock(id))));
  }),

  http.get(url("/api/inventory/stock/:id"), ({ params, request }) =>
    HttpResponse.json(stockFor(bearer(request))(db.getStock(String(params.id)))),
  ),

  http.put(url("/api/inventory/stock/:id"), async ({ params, request }) => {
    await delay(LATENCY);
    const account = bearer(request);
    if (!account) return unauthorized();
    const scope = writeScope(account);
    const id = String(params.id);
    if (!scope || !db.canWriteProduct(id, scope.merchantId)) return forbidden();
    const body = (await request.json()) as { available?: unknown };
    if (!Number.isInteger(body.available) || (body.available as number) < 0)
      return HttpResponse.json(
        {
          detail: [
            {
              type: "greater_than_equal",
              loc: ["body", "available"],
              msg: "Input should be greater than or equal to 0",
            },
          ],
        },
        { status: 422 },
      );
    db.setStock(id, body.available as number);
    return HttpResponse.json(db.getStock(id));
  }),

  http.post(url("/api/catalog/products"), async ({ request }) => {
    await delay(LATENCY * 2);
    const account = bearer(request);
    if (!account) return unauthorized();
    const scope = writeScope(account);
    if (!scope) return forbidden();
    const body = (await request.json()) as Parameters<typeof db.createProduct>[1] & {
      merchant_id?: string;
    };
    const merchantId = scope.merchantId ?? body.merchant_id;
    if (!merchantId)
      return HttpResponse.json({ detail: "merchant_id is required" }, { status: 422 });
    const res = db.createProduct(merchantId, body);
    return res.ok
      ? HttpResponse.json(res.value, { status: 201 })
      : HttpResponse.json({ detail: res.detail }, { status: res.status });
  }),

  http.patch(url("/api/catalog/products/:id"), async ({ params, request }) => {
    await delay(LATENCY);
    const account = bearer(request);
    if (!account) return unauthorized();
    const scope = writeScope(account);
    const id = String(params.id);
    if (!PRODUCTS.some((p) => p.id === id)) return notFound("product not found");
    if (!scope || !db.canWriteProduct(id, scope.merchantId)) return forbidden();
    const res = db.patchProduct(
      id,
      (await request.json()) as Parameters<typeof db.patchProduct>[1],
    );
    return res.ok
      ? HttpResponse.json(res.value)
      : HttpResponse.json({ detail: res.detail }, { status: res.status });
  }),

  http.delete(url("/api/catalog/products/:id"), async ({ params, request }) => {
    await delay(LATENCY);
    const account = bearer(request);
    if (!account) return unauthorized();
    const scope = writeScope(account);
    const id = String(params.id);
    if (PRODUCTS.some((p) => p.id === id) && (!scope || !db.canWriteProduct(id, scope.merchantId)))
      return forbidden();
    db.deactivateProduct(id);
    return new HttpResponse(null, { status: 204 });
  }),

  http.get(url("/api/orders/merchant"), async ({ request }) => {
    await delay(LATENCY);
    const account = bearer(request);
    if (!account) return unauthorized();
    const allowed = account.roles.includes("merchant") || account.roles.includes("admin");
    if (!allowed) return forbidden();
    if (!account.merchant_id)
      return HttpResponse.json({ detail: "no merchant bound to this account" }, { status: 403 });
    const sp = new URL(request.url).searchParams;
    const pageSize = Number(sp.get("page_size") ?? 20);
    if (pageSize > 50)
      return HttpResponse.json(
        {
          detail: [
            {
              type: "less_than_equal",
              loc: ["query", "page_size"],
              msg: "Input should be less than or equal to 50",
            },
          ],
        },
        { status: 422 },
      );
    return HttpResponse.json(
      paginate(
        db.merchantOrders(account.merchant_id),
        Math.max(1, Number(sp.get("page") ?? 1)),
        pageSize,
      ),
    );
  }),

  http.post(url("/api/orders"), async ({ request }) => {
    await delay(LATENCY * 3);
    const key = request.headers.get("Idempotency-Key");
    if (!key)
      return HttpResponse.json({ detail: "Idempotency-Key é obrigatório" }, { status: 400 });
    const body = (await request.json()) as Parameters<typeof db.createOrder>[0];
    try {
      const { id } = db.createOrder(body, key);
      if (
        /cobranca lenta/i.test(
          `${body.customer_name} ${body.customer_email}`
            .normalize("NFD")
            .replace(/\p{Diacritic}/gu, ""),
        )
      ) {
        pendingCharges.add(id);
      }
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
    const orderId = String(params.orderId);
    const p = db.getPayment(orderId);
    if (!p && db.getOrder(orderId)?.status === "PENDING" && pendingCharges.has(orderId)) {
      pendingCharges.delete(orderId);
      return HttpResponse.json(
        { detail: "payment is being created" },
        { status: 202, headers: { "Retry-After": "1" } },
      );
    }
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
