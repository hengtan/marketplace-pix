import type {
  LedgerEntry,
  MerchantOrder,
  MerchantSummary,
  Notification,
  Order,
  Payment,
  Product,
} from "@/api/schemas";
import { SEED_MERCHANTS } from "@/lib/merchants";
import { uuid } from "@/lib/uuid";
import { CATEGORY_LABELS, INITIAL_STOCK, PRODUCTS } from "./data";

const PIX_TTL_MS = 10 * 60 * 1000;
const SHORT_TTL_MS = 25 * 1000;
const STOCK_REJECT_DELAY_MS = 1500;
const DAY = 86_400_000;

interface Stock {
  available: number;
  reserved: number;
}

type CatalogOp =
  | { op: "create"; product: Product }
  | { op: "patch"; id: string; patch: Partial<Product> }
  | { op: "deactivate"; id: string };

const ORIGINAL_PRODUCTS = PRODUCTS.map((p) => ({ ...p, tags: [...p.tags] }));
const retiredSlugs = new Set<string>();

function resetCatalog() {
  PRODUCTS.splice(
    0,
    PRODUCTS.length,
    ...ORIGINAL_PRODUCTS.map((p) => ({ ...p, tags: [...p.tags] })),
  );
  retiredSlugs.clear();
}

function applyOp(op: CatalogOp) {
  if (op.op === "create") {
    PRODUCTS.unshift(op.product);
  } else if (op.op === "patch") {
    const p = PRODUCTS.find((x) => x.id === op.id);
    if (p) Object.assign(p, op.patch);
  } else {
    const i = PRODUCTS.findIndex((x) => x.id === op.id);
    const removed = i >= 0 ? PRODUCTS.splice(i, 1)[0] : undefined;
    if (removed) retiredSlugs.add(removed.slug);
  }
}

interface DbState {
  catalogLog: CatalogOp[];
  stock: Map<string, Stock>;
  orders: Map<string, Order>;
  payments: Map<string, Payment>;
  idempotency: Map<string, string>;
  notifications: Notification[];
  notificationHtml: Map<string, string>;
  entries: Map<string, LedgerEntry[]>;
  liveDaily: Map<string, { gross: number; net: number; orders: number }>;
  seedDaily: Map<
    string,
    { date: string; gross_cents: number; net_cents: number; orders: number }[]
  >;
  rejectAt: Map<string, number>;
}

function seeded(n: number): number {
  const x = Math.sin(n * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}

function dayKey(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

const CUSTOMERS = [
  "Maria Souza",
  "João Pereira",
  "Ana Beatriz Lima",
  "Carlos Eduardo Ramos",
  "Fernanda Costa",
  "Rafael Almeida",
  "Juliana Martins",
  "Pedro Henrique Dias",
  "Camila Rocha",
  "Lucas Barbosa",
  "Patrícia Nogueira",
  "Thiago Moreira",
];

function seedMerchantOrders(
  state: DbState,
  merchantId: string,
  mi: number,
  daily: { orders: number }[],
  now: number,
) {
  const catalog = PRODUCTS.filter((p) => p.merchant.id === merchantId);
  if (catalog.length === 0) return;
  let n = 0;
  const make = (ms: number, status: Order["status"]) => {
    n += 1;
    const first = catalog[Math.floor(seeded(n * 7 + mi) * catalog.length)] as Product;
    const second = catalog[Math.floor(seeded(n * 13 + mi) * catalog.length)] as Product;
    const lines = [{ p: first, q: 1 + Math.floor(seeded(n * 3) * 3) }];
    if (seeded(n * 5 + mi) > 0.7 && second.id !== first.id) lines.push({ p: second, q: 1 });
    const items = lines.map(({ p, q }) => ({
      product_id: p.id,
      merchant_id: p.merchant.id,
      quantity: q,
      unit_price_cents: p.price_cents,
    }));
    const order: Order = {
      id: uuid(),
      customer_id: "seed-customer",
      customer_name: CUSTOMERS[Math.floor(seeded(n * 11 + mi) * CUSTOMERS.length)] as string,
      customer_email: "cliente@exemplo.com",
      status,
      currency: "BRL",
      total_cents: items.reduce((t, i) => t + i.quantity * i.unit_price_cents, 0),
      created_at: new Date(ms).toISOString(),
      cancel_reason: status === "CANCELLED" ? "payment expired" : null,
      items,
    };
    state.orders.set(order.id, order);
  };
  for (let d = 13; d >= 0; d--) {
    const count = Math.min(6, daily[daily.length - 1 - d]?.orders ?? 0);
    for (let k = 0; k < count; k++) {
      const hours = d === 0 ? 1 + k * 0.5 : 8 + seeded(d * 17 + k + mi) * 13;
      const ms = d === 0 ? now - hours * 3_600_000 : now - d * DAY + (hours - 12) * 3_600_000;
      make(ms, seeded(d * 29 + k * 7 + mi) > 0.86 ? "CANCELLED" : "PAID");
    }
  }
  if (mi === SEED_MERCHANTS.length - 1) {
    make(now - 7 * 60_000, "PENDING");
    make(now - 40_000, "PENDING");
  }
}

function createState(): DbState {
  resetCatalog();
  const state: DbState = {
    catalogLog: [],
    stock: new Map(),
    orders: new Map(),
    payments: new Map(),
    idempotency: new Map(),
    notifications: [],
    notificationHtml: new Map(),
    entries: new Map(),
    liveDaily: new Map(),
    seedDaily: new Map(),
    rejectAt: new Map(),
  };
  for (const [id, available] of Object.entries(INITIAL_STOCK)) {
    state.stock.set(id, { available, reserved: 0 });
  }
  const now = Date.now();
  SEED_MERCHANTS.forEach((m, mi) => {
    const daily: DbState["seedDaily"] extends Map<string, infer V> ? V : never = [];
    const entries: LedgerEntry[] = [];
    for (let d = 59; d >= 0; d--) {
      const ms = now - d * DAY;
      const orders = Math.round(1 + seeded(d + mi * 61) * 5 + (60 - d) / 18);
      const gross = orders * Math.round(8000 + seeded(d * 3 + mi) * 30000);
      const fee = Math.round(gross * 0.1);
      daily.push({ date: dayKey(ms), gross_cents: gross, net_cents: gross - fee, orders });
      if (d < 14) {
        entries.push({
          id: uuid(),
          transaction_id: uuid(),
          direction: "CREDIT",
          amount_cents: gross - fee,
          description: `Vendas do dia, ${orders} pedidos`,
          order_id: null,
          created_at: new Date(ms).toISOString(),
        });
      }
    }
    state.seedDaily.set(m.id, daily);
    state.entries.set(m.id, entries.reverse());
    seedMerchantOrders(state, m.id, mi, daily, now);
  });
  return state;
}

const STORAGE_KEY = "praca-mock-db-v2";
const MAPS = [
  "stock",
  "orders",
  "payments",
  "idempotency",
  "notificationHtml",
  "entries",
  "liveDaily",
  "seedDaily",
  "rejectAt",
] as const;

function hydrate(): DbState | null {
  if (typeof localStorage === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as Record<string, unknown>;
    const next = createState();
    for (const key of MAPS) {
      (next as unknown as Record<string, unknown>)[key] = new Map(data[key] as [string, unknown][]);
    }
    next.notifications = data.notifications as Notification[];
    next.catalogLog = (data.catalogLog as CatalogOp[] | undefined) ?? [];
    for (const op of next.catalogLog) applyOp(op);
    return next;
  } catch {
    return null;
  }
}

function persist() {
  if (typeof localStorage === "undefined" || !persistEnabled) return;
  try {
    const out: Record<string, unknown> = {
      notifications: state.notifications,
      catalogLog: state.catalogLog,
    };
    for (const key of MAPS) out[key] = [...(state[key] as Map<string, unknown>).entries()];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(out));
  } catch {
    /* storage full or unavailable */
  }
}

let persistEnabled = false;
let state = createState();

export function enableMockPersistence() {
  persistEnabled = true;
  state = hydrate() ?? state;
  persist();
}

export function resetDb() {
  state = createState();
  persist();
}

function nowIso() {
  return new Date().toISOString();
}

function pushNotification(order: Order, kind: Notification["kind"], subject: string, html: string) {
  const id = uuid();
  state.notifications.unshift({
    id,
    kind,
    subject,
    status: "SENT",
    order_id: order.id,
    created_at: nowIso(),
    sent_at: nowIso(),
  });
  state.notificationHtml.set(id, html);
}

function emailHtml(title: string, body: string, order: Order): string {
  const total = (order.total_cents / 100).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
  return `<!doctype html><html lang="pt-BR"><body style="margin:0;background:#f3f5fb;font-family:system-ui,sans-serif;color:#141a3a"><div style="max-width:520px;margin:32px auto;background:#fff;border-radius:16px;padding:32px"><div style="font-weight:700;color:#2b3df0;font-size:20px">Praça</div><h1 style="font-size:24px;margin:24px 0 8px">${title}</h1><p style="line-height:1.6;color:#4b5280">${body}</p><div style="margin-top:24px;padding:16px;border-radius:12px;background:#eef0fc"><div style="font-size:13px;color:#4b5280">Pedido ${order.id.slice(0, 8).toUpperCase()}</div><div style="font-size:22px;font-weight:700">${total}</div></div></div></body></html>`;
}

export function listProducts(): Product[] {
  return PRODUCTS;
}

export function getStock(productId: string): {
  product_id: string;
  available: number;
  reserved: number;
} {
  const s = state.stock.get(productId) ?? { available: 0, reserved: 0 };
  return { product_id: productId, ...s };
}

export function setStock(productId: string, available: number) {
  const s = state.stock.get(productId) ?? { available: 0, reserved: 0 };
  state.stock.set(productId, { ...s, available });
  persist();
}

export function createOrder(
  input: {
    customer_id: string;
    customer_name: string;
    customer_email: string;
    items: { product_id: string; quantity: number }[];
  },
  key: string,
): { id: string; replay: boolean } {
  const existing = state.idempotency.get(key);
  if (existing) return { id: existing, replay: true };

  const items = input.items.map((i) => {
    const p = PRODUCTS.find((x) => x.id === i.product_id);
    if (!p) throw new Error(`Produto não encontrado: ${i.product_id}`);
    return {
      product_id: p.id,
      merchant_id: p.merchant.id,
      quantity: i.quantity,
      unit_price_cents: p.price_cents,
    };
  });
  const total = items.reduce((n, i) => n + i.quantity * i.unit_price_cents, 0);
  const order: Order = {
    id: uuid(),
    customer_id: input.customer_id,
    customer_name: input.customer_name,
    customer_email: input.customer_email,
    status: "PENDING",
    currency: "BRL",
    total_cents: total,
    created_at: nowIso(),
    cancel_reason: null,
    items,
  };
  state.orders.set(order.id, order);
  state.idempotency.set(key, order.id);
  pushNotification(
    order,
    "ORDER_CREATED",
    "Recebemos o seu pedido",
    emailHtml("Recebemos o seu pedido", "Assim que o PIX for pago, avisamos por aqui.", order),
  );

  const insufficient = items.some(
    (i) => (state.stock.get(i.product_id)?.available ?? 0) < i.quantity,
  );
  if (insufficient) {
    state.rejectAt.set(order.id, Date.now() + STOCK_REJECT_DELAY_MS);
    persist();
    return { id: order.id, replay: false };
  }
  for (const i of items) {
    const s = state.stock.get(i.product_id);
    if (s)
      state.stock.set(i.product_id, { available: s.available, reserved: s.reserved + i.quantity });
  }
  const short = /expira/i.test(input.customer_email) || /expira/i.test(input.customer_name);
  const payment: Payment = {
    id: uuid(),
    order_id: order.id,
    status: "PENDING",
    amount_cents: total,
    currency: "BRL",
    pix_code: `00020126580014BR.GOV.BCB.PIX0136${uuid()}5204000053039865406${(total / 100).toFixed(2)}5802BR5905PRACA6009SAO PAULO62070503***6304${Math.floor(
      Math.random() * 65535,
    )
      .toString(16)
      .toUpperCase()
      .padStart(4, "0")}`,
    psp_charge_id: `ch_${uuid().replace(/-/g, "").slice(0, 18)}`,
    expires_at: new Date(Date.now() + (short ? SHORT_TTL_MS : PIX_TTL_MS)).toISOString(),
    confirmed_at: null,
  };
  state.payments.set(order.id, payment);
  pushNotification(
    order,
    "PIX_READY",
    "Seu PIX está pronto para pagar",
    emailHtml(
      "Seu PIX está pronto",
      "Copie o código ou leia o QR Code no app do seu banco.",
      order,
    ),
  );
  persist();
  return { id: order.id, replay: false };
}

function release(order: Order) {
  for (const i of order.items) {
    const s = state.stock.get(i.product_id);
    if (s) state.stock.set(i.product_id, { ...s, reserved: Math.max(0, s.reserved - i.quantity) });
  }
}

function cancel(order: Order, reason: string) {
  order.status = "CANCELLED";
  order.cancel_reason = reason;
  pushNotification(
    order,
    "ORDER_CANCELLED",
    "Seu pedido foi cancelado",
    emailHtml(
      "Pedido cancelado",
      "Nenhum valor foi cobrado. Você pode refazer a compra quando quiser.",
      order,
    ),
  );
}

function tick(order: Order) {
  if (order.status !== "PENDING") return;
  const rejectAt = state.rejectAt.get(order.id);
  if (rejectAt && Date.now() >= rejectAt) {
    state.rejectAt.delete(order.id);
    cancel(order, "out of stock");
    persist();
    return;
  }
  const payment = state.payments.get(order.id);
  if (
    payment &&
    payment.status === "PENDING" &&
    Date.now() >= new Date(payment.expires_at).getTime()
  ) {
    payment.status = "EXPIRED";
    release(order);
    cancel(order, "payment expired");
    persist();
  }
}

export function getOrder(id: string): Order | undefined {
  const order = state.orders.get(id);
  if (order) tick(order);
  return order;
}

export function listOrders(customerId: string): Order[] {
  const list = [...state.orders.values()].filter((o) => o.customer_id === customerId);
  for (const o of list) tick(o);
  return list.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function getPayment(orderId: string): Payment | undefined {
  const order = state.orders.get(orderId);
  if (order) tick(order);
  return state.payments.get(orderId);
}

export function payCharge(chargeId: string): boolean {
  const payment = [...state.payments.values()].find((p) => p.psp_charge_id === chargeId);
  if (payment?.status !== "PENDING") return false;
  const order = state.orders.get(payment.order_id);
  if (order?.status !== "PENDING") return false;
  payment.status = "CONFIRMED";
  payment.confirmed_at = nowIso();
  order.status = "PAID";
  for (const i of order.items) {
    const s = state.stock.get(i.product_id);
    if (s) {
      state.stock.set(i.product_id, {
        available: Math.max(0, s.available - i.quantity),
        reserved: Math.max(0, s.reserved - i.quantity),
      });
    }
  }
  const byMerchant = new Map<string, number>();
  for (const i of order.items) {
    byMerchant.set(
      i.merchant_id,
      (byMerchant.get(i.merchant_id) ?? 0) + i.quantity * i.unit_price_cents,
    );
  }
  const txId = uuid();
  const today = dayKey(Date.now());
  for (const [merchantId, gross] of byMerchant) {
    const fee = Math.round(gross * 0.1);
    const list = state.entries.get(merchantId) ?? [];
    list.unshift({
      id: uuid(),
      transaction_id: txId,
      direction: "CREDIT",
      amount_cents: gross - fee,
      description: `Venda do pedido ${order.id.slice(0, 8).toUpperCase()}`,
      order_id: order.id,
      created_at: nowIso(),
    });
    state.entries.set(merchantId, list);
    const key = `${merchantId}:${today}`;
    const live = state.liveDaily.get(key) ?? { gross: 0, net: 0, orders: 0 };
    state.liveDaily.set(key, {
      gross: live.gross + gross,
      net: live.net + gross - fee,
      orders: live.orders + 1,
    });
  }
  pushNotification(
    order,
    "ORDER_PAID",
    "Pagamento confirmado",
    emailHtml("Pagamento confirmado", "Recebemos o seu PIX. Obrigado pela compra!", order),
  );
  persist();
  return true;
}

export function listNotifications(customerId: string): Notification[] {
  const ids = new Set(
    [...state.orders.values()].filter((o) => o.customer_id === customerId).map((o) => o.id),
  );
  return state.notifications.filter((n) => n.order_id && ids.has(n.order_id));
}

export function notificationHtml(id: string): string | undefined {
  return state.notificationHtml.get(id);
}

export function merchantSummary(merchantId: string, days: number): MerchantSummary {
  const seed = state.seedDaily.get(merchantId) ?? [];
  const daily = seed.slice(-days).map((d) => {
    const live = state.liveDaily.get(`${merchantId}:${d.date}`);
    return live
      ? {
          ...d,
          gross_cents: d.gross_cents + live.gross,
          net_cents: d.net_cents + live.net,
          orders: d.orders + live.orders,
        }
      : d;
  });
  const gross = daily.reduce((n, d) => n + d.gross_cents, 0);
  const net = daily.reduce((n, d) => n + d.net_cents, 0);
  return {
    merchant_id: merchantId,
    currency: "BRL",
    balance_cents: net,
    gross_sales_cents: gross,
    platform_fees_cents: gross - net,
    net_sales_cents: net,
    orders_count: daily.reduce((n, d) => n + d.orders, 0),
    daily,
  };
}

export function merchantEntries(merchantId: string): LedgerEntry[] {
  return state.entries.get(merchantId) ?? [];
}

export function reconciliation() {
  let debits = 0;
  let credits = 0;
  for (const list of state.entries.values()) {
    for (const e of list) {
      if (e.direction === "CREDIT") credits += e.amount_cents;
      else debits += e.amount_cents;
    }
  }
  const platformFees = Math.round(credits / 9);
  return {
    balanced: true,
    total_debits_cents: credits + platformFees,
    total_credits_cents: credits + platformFees,
    transactions_count: [...state.entries.values()].reduce((n, l) => n + l.length, 0) + debits * 0,
    checked_at: nowIso(),
  };
}

function ownedBy(productId: string, merchantId: string | null): boolean {
  const p = PRODUCTS.find((x) => x.id === productId);
  return Boolean(p) && (merchantId === null || p?.merchant.id === merchantId);
}

export function merchantStock(merchantId: string) {
  return PRODUCTS.filter((p) => p.merchant.id === merchantId).map((p) => getStock(p.id));
}

export function merchantOrders(merchantId: string): MerchantOrder[] {
  const out: MerchantOrder[] = [];
  for (const order of state.orders.values()) {
    tick(order);
    const items = order.items.filter((i) => i.merchant_id === merchantId);
    if (items.length === 0) continue;
    out.push({
      id: order.id,
      status: order.status,
      currency: order.currency,
      created_at: order.created_at,
      customer_name: order.customer_name,
      subtotal_cents: items.reduce((n, i) => n + i.quantity * i.unit_price_cents, 0),
      items,
    });
  }
  return out.sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function canWriteProduct(productId: string, merchantId: string | null): boolean {
  return ownedBy(productId, merchantId);
}

function slugify(name: string): string {
  return name
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

export type CatalogResult<T> =
  | { ok: true; value: T }
  | { ok: false; status: number; detail: string };

export function createProduct(
  merchantId: string,
  input: {
    name: string;
    description: string;
    price_cents: number;
    category: string;
    tags?: string[];
    image_url?: string | null;
  },
): CatalogResult<Product> {
  const merchant = SEED_MERCHANTS.find((m) => m.id === merchantId);
  if (!merchant) return { ok: false, status: 422, detail: "merchant not found" };
  if (!(input.name?.trim().length > 0))
    return {
      ok: false,
      status: 422,
      detail: "invalid body.name: String should have at least 1 character",
    };
  if (!Number.isInteger(input.price_cents) || input.price_cents <= 0)
    return {
      ok: false,
      status: 422,
      detail: "invalid body.price_cents: Input should be greater than 0",
    };
  if (!(input.category in CATEGORY_LABELS))
    return { ok: false, status: 422, detail: "unknown category" };
  const slug = slugify(input.name);
  const sameName = (p: Product) =>
    slugify(p.name) === slug || p.name.trim().toLowerCase() === input.name.trim().toLowerCase();
  if (PRODUCTS.some((p) => p.slug === slug || sameName(p)) || retiredSlugs.has(slug))
    return { ok: false, status: 409, detail: "slug already in use" };
  const product: Product = {
    id: uuid(),
    slug,
    name: input.name.trim(),
    description: input.description,
    price_cents: input.price_cents,
    currency: "BRL",
    category: input.category,
    image_url: input.image_url ?? null,
    rating: 0,
    reviews_count: 0,
    tags: input.tags ?? [],
    merchant: { id: merchant.id, slug: merchant.slug, name: merchant.name },
    created_at: nowIso(),
  };
  const op: CatalogOp = { op: "create", product };
  applyOp(op);
  state.catalogLog.push(op);
  state.stock.set(product.id, { available: 0, reserved: 0 });
  persist();
  return { ok: true, value: product };
}

export function patchProduct(
  id: string,
  patch: Partial<Pick<Product, "name" | "description" | "price_cents" | "category" | "tags">>,
): CatalogResult<Product> {
  const product = PRODUCTS.find((p) => p.id === id);
  if (!product) return { ok: false, status: 404, detail: "product not found" };
  const clean = Object.fromEntries(Object.entries(patch).filter(([, v]) => v !== undefined));
  if (Object.keys(clean).length === 0)
    return { ok: false, status: 422, detail: "no fields to change" };
  if (
    "price_cents" in clean &&
    (!Number.isInteger(clean.price_cents) || (clean.price_cents as number) <= 0)
  )
    return {
      ok: false,
      status: 422,
      detail: "invalid body.price_cents: Input should be greater than 0",
    };
  const op: CatalogOp = { op: "patch", id, patch: clean };
  applyOp(op);
  state.catalogLog.push(op);
  persist();
  return { ok: true, value: product };
}

export function deactivateProduct(id: string) {
  if (!PRODUCTS.some((p) => p.id === id)) return;
  const op: CatalogOp = { op: "deactivate", id };
  applyOp(op);
  state.catalogLog.push(op);
  persist();
}
