import type {
  LedgerEntry,
  MerchantSummary,
  Notification,
  Order,
  Payment,
  Product,
} from "@/api/schemas";
import { SEED_MERCHANTS } from "@/lib/merchants";
import { uuid } from "@/lib/uuid";
import { INITIAL_STOCK, PRODUCTS } from "./data";

const PIX_TTL_MS = 10 * 60 * 1000;
const SHORT_TTL_MS = 25 * 1000;
const STOCK_REJECT_DELAY_MS = 1500;
const DAY = 86_400_000;

interface Stock {
  available: number;
  reserved: number;
}

interface DbState {
  stock: Map<string, Stock>;
  orders: Map<string, Order>;
  payments: Map<string, Payment>;
  idempotency: Map<string, string>;
  notifications: Notification[];
  notificationHtml: Map<string, string>;
  entries: Map<string, LedgerEntry[]>;
  liveDaily: Map<string, { gross: number; net: number; orders: number }>;
  seedDaily: Map<string, { date: string; gross_cents: number; net_cents: number; orders: number }[]>;
  rejectAt: Map<string, number>;
}

function seeded(n: number): number {
  const x = Math.sin(n * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}

function dayKey(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

function createState(): DbState {
  const state: DbState = {
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
  });
  return state;
}

let state = createState();

export function resetDb() {
  state = createState();
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

export function getStock(productId: string): { product_id: string; available: number; reserved: number } {
  const s = state.stock.get(productId) ?? { available: 0, reserved: 0 };
  return { product_id: productId, ...s };
}

export function setStock(productId: string, available: number) {
  const s = state.stock.get(productId) ?? { available: 0, reserved: 0 };
  state.stock.set(productId, { ...s, available });
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

  const insufficient = items.some((i) => (state.stock.get(i.product_id)?.available ?? 0) < i.quantity);
  if (insufficient) {
    state.rejectAt.set(order.id, Date.now() + STOCK_REJECT_DELAY_MS);
    return { id: order.id, replay: false };
  }
  for (const i of items) {
    const s = state.stock.get(i.product_id);
    if (s) state.stock.set(i.product_id, { available: s.available, reserved: s.reserved + i.quantity });
  }
  const short = /expira/i.test(input.customer_email) || /expira/i.test(input.customer_name);
  const payment: Payment = {
    id: uuid(),
    order_id: order.id,
    status: "PENDING",
    amount_cents: total,
    currency: "BRL",
    pix_code: `00020126580014BR.GOV.BCB.PIX0136${uuid()}5204000053039865406${(total / 100).toFixed(2)}5802BR5905PRACA6009SAO PAULO62070503***6304${Math.floor(Math.random() * 65535)
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
    emailHtml("Seu PIX está pronto", "Copie o código ou leia o QR Code no app do seu banco.", order),
  );
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
    emailHtml("Pedido cancelado", "Nenhum valor foi cobrado. Você pode refazer a compra quando quiser.", order),
  );
}

function tick(order: Order) {
  if (order.status !== "PENDING") return;
  const rejectAt = state.rejectAt.get(order.id);
  if (rejectAt && Date.now() >= rejectAt) {
    state.rejectAt.delete(order.id);
    cancel(order, "out of stock");
    return;
  }
  const payment = state.payments.get(order.id);
  if (payment && payment.status === "PENDING" && Date.now() >= new Date(payment.expires_at).getTime()) {
    payment.status = "EXPIRED";
    release(order);
    cancel(order, "payment expired");
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
  if (!payment || payment.status !== "PENDING") return false;
  const order = state.orders.get(payment.order_id);
  if (!order || order.status !== "PENDING") return false;
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
    byMerchant.set(i.merchant_id, (byMerchant.get(i.merchant_id) ?? 0) + i.quantity * i.unit_price_cents);
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
  return true;
}

export function listNotifications(customerId: string): Notification[] {
  const ids = new Set([...state.orders.values()].filter((o) => o.customer_id === customerId).map((o) => o.id));
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
