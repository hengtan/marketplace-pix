import type { MerchantOrder } from "@/api/merchant";
import type { LedgerEntry, MerchantSummary, Stock } from "@/api/schemas";

export type Daily = MerchantSummary["daily"][number];

export const LOW_STOCK = 5;
export const STALE_PENDING_MS = 5 * 60_000;
export const DROP_ALERT = -0.2;
export const SALES_WINDOW_DAYS = 14;

export interface Totals {
  gross: number;
  net: number;
  fees: number;
  orders: number;
  ticket: number;
  feeRate: number;
}

export interface Comparison {
  current: Totals;
  previous: Totals;
  hasPrevious: boolean;
  deltas: {
    gross: number | null;
    net: number | null;
    orders: number | null;
    ticket: number | null;
    feeRate: number | null;
  };
}

export function pctChange(current: number, previous: number): number | null {
  if (previous === 0) return current === 0 ? 0 : null;
  return (current - previous) / Math.abs(previous);
}

export function totalsOf(daily: Daily[]): Totals {
  let gross = 0;
  let net = 0;
  let orders = 0;
  for (const d of daily) {
    gross += d.gross_cents;
    net += d.net_cents;
    orders += d.orders;
  }
  const fees = gross - net;
  return {
    gross,
    net,
    fees,
    orders,
    ticket: orders > 0 ? Math.round(gross / orders) : 0,
    feeRate: gross > 0 ? fees / gross : 0,
  };
}

export function splitPeriods(
  daily: Daily[],
  days: number,
): { current: Daily[]; previous: Daily[] } {
  const sorted = [...daily].sort((a, b) => a.date.localeCompare(b.date));
  const current = sorted.slice(-days);
  const previous = sorted.slice(
    Math.max(0, sorted.length - days * 2),
    sorted.length - current.length,
  );
  return { current, previous };
}

export function comparePeriods(daily: Daily[], days: number): Comparison {
  const { current, previous } = splitPeriods(daily, days);
  const cur = totalsOf(current);
  const prev = totalsOf(previous);
  const hasPrevious = previous.length >= days && prev.gross + prev.orders > 0;
  const rate = (a: number, b: number) => (hasPrevious ? pctChange(a, b) : null);
  return {
    current: cur,
    previous: prev,
    hasPrevious,
    deltas: {
      gross: rate(cur.gross, prev.gross),
      net: rate(cur.net, prev.net),
      orders: rate(cur.orders, prev.orders),
      ticket: rate(cur.ticket, prev.ticket),
      feeRate: hasPrevious ? cur.feeRate - prev.feeRate : null,
    },
  };
}

export function formatPct(value: number, digits = 1): string {
  const text = new Intl.NumberFormat("pt-BR", {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Math.abs(value));
  if (Math.abs(value) < 0.5 * 10 ** -(digits + 2)) return text;
  return `${value > 0 ? "+" : "-"}${text}`;
}

export function movingAverage(values: number[], window: number): number[] {
  const size = Math.max(1, Math.floor(window));
  return values.map((_, i) => {
    const slice = values.slice(Math.max(0, i - size + 1), i + 1);
    return Math.round(slice.reduce((n, v) => n + v, 0) / slice.length);
  });
}

export const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"] as const;
export const WEEKDAYS_LONG = [
  "domingo",
  "segunda-feira",
  "terça-feira",
  "quarta-feira",
  "quinta-feira",
  "sexta-feira",
  "sábado",
] as const;

export function weekdayOf(isoDate: string): number {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1)).getUTCDay();
}

export interface WeekdayStat {
  weekday: number;
  gross: number;
  orders: number;
  occurrences: number;
  avgGross: number;
}

export function weekdayAggregate(daily: Daily[]): WeekdayStat[] {
  const stats: WeekdayStat[] = Array.from({ length: 7 }, (_, weekday) => ({
    weekday,
    gross: 0,
    orders: 0,
    occurrences: 0,
    avgGross: 0,
  }));
  for (const d of daily) {
    const s = stats[weekdayOf(d.date)];
    if (!s) continue;
    s.gross += d.gross_cents;
    s.orders += d.orders;
    s.occurrences += 1;
  }
  for (const s of stats) s.avgGross = s.occurrences > 0 ? Math.round(s.gross / s.occurrences) : 0;
  return stats;
}

export function bestWeekday(stats: WeekdayStat[]): WeekdayStat | null {
  const best = [...stats].sort((a, b) => b.avgGross - a.avgGross)[0];
  return best && best.avgGross > 0 ? best : null;
}

export function bestDay(daily: Daily[]): Daily | null {
  const best = [...daily].sort((a, b) => b.gross_cents - a.gross_cents)[0];
  return best && best.gross_cents > 0 ? best : null;
}

export type CalendarCell = Daily | null;

export function calendarGrid(daily: Daily[]): CalendarCell[][] {
  const sorted = [...daily].sort((a, b) => a.date.localeCompare(b.date));
  const first = sorted[0];
  if (!first) return [];
  const cells: CalendarCell[] = Array.from({ length: weekdayOf(first.date) }, () => null);
  cells.push(...sorted);
  while (cells.length % 7 !== 0) cells.push(null);
  const rows: CalendarCell[][] = [];
  for (let i = 0; i < cells.length; i += 7) rows.push(cells.slice(i, i + 7));
  return rows;
}

export function heatLevel(value: number, max: number): number {
  if (max <= 0 || value <= 0) return 0;
  return Math.min(4, Math.max(1, Math.ceil((value / max) * 4)));
}

export type OrderStatusKey = "PENDING" | "PAID" | "CANCELLED";

export function orderStatus(status: string): OrderStatusKey {
  if (status === "PAID") return "PAID";
  if (status === "PENDING") return "PENDING";
  return "CANCELLED";
}

export const ORDER_STATUS_LABEL: Record<OrderStatusKey, string> = {
  PENDING: "Aguardando PIX",
  PAID: "Pago",
  CANCELLED: "Cancelado",
};

export type StatusFilter = "ALL" | OrderStatusKey;

export function normalize(s: string): string {
  return s
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

export function orderUnits(order: MerchantOrder): number {
  return order.items.reduce((n, i) => n + i.quantity, 0);
}

export function filterOrders(
  orders: MerchantOrder[],
  opts: {
    status: StatusFilter;
    query: string;
    names?: Record<string, string>;
    sinceMs?: number;
  },
): MerchantOrder[] {
  const q = normalize(opts.query.trim());
  return orders.filter((o) => {
    if (opts.status !== "ALL" && orderStatus(o.status) !== opts.status) return false;
    if (opts.sinceMs !== undefined && new Date(o.created_at).getTime() < opts.sinceMs) return false;
    if (!q) return true;
    const haystack = normalize(
      [o.id, o.customer_name, ...o.items.map((i) => opts.names?.[i.product_id] ?? "")].join(" "),
    );
    return haystack.includes(q);
  });
}

export function countByStatus(orders: MerchantOrder[]): Record<StatusFilter, number> {
  const out: Record<StatusFilter, number> = {
    ALL: orders.length,
    PENDING: 0,
    PAID: 0,
    CANCELLED: 0,
  };
  for (const o of orders) out[orderStatus(o.status)] += 1;
  return out;
}

export function paginate<T>(items: T[], page: number, size: number) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(1, page), pages);
  return { items: items.slice((current - 1) * size, current * size), page: current, pages };
}

export interface OrderChanges {
  created: MerchantOrder[];
  paid: MerchantOrder[];
}

export function detectOrderChanges(
  known: ReadonlyMap<string, string> | null,
  orders: MerchantOrder[],
): OrderChanges {
  if (!known) return { created: [], paid: [] };
  const created: MerchantOrder[] = [];
  const paid: MerchantOrder[] = [];
  for (const o of orders) {
    const before = known.get(o.id);
    if (before === undefined) {
      if (orderStatus(o.status) === "PAID") paid.push(o);
      else created.push(o);
    } else if (orderStatus(before) !== "PAID" && orderStatus(o.status) === "PAID") paid.push(o);
  }
  return { created, paid };
}

export function snapshotStatuses(orders: MerchantOrder[]): Map<string, string> {
  return new Map(orders.map((o) => [o.id, o.status]));
}

export type StockLevel = "out" | "critical" | "attention" | "healthy";

export interface StockRow {
  productId: string;
  available: number;
  reserved: number;
  dailyRate: number;
  coverageDays: number | null;
  fill: number;
  level: StockLevel;
}

export function dailySalesRate(
  orders: MerchantOrder[],
  now: number,
  windowDays = SALES_WINDOW_DAYS,
): Map<string, number> {
  const since = now - windowDays * 86_400_000;
  const units = new Map<string, number>();
  for (const o of orders) {
    if (orderStatus(o.status) !== "PAID") continue;
    if (new Date(o.created_at).getTime() < since) continue;
    for (const i of o.items) units.set(i.product_id, (units.get(i.product_id) ?? 0) + i.quantity);
  }
  return new Map([...units].map(([id, n]) => [id, n / windowDays]));
}

export function stockLevel(available: number, coverageDays: number | null): StockLevel {
  if (available <= 0) return "out";
  if (available <= LOW_STOCK || (coverageDays !== null && coverageDays < 3)) return "critical";
  if (coverageDays !== null && coverageDays < 7) return "attention";
  return "healthy";
}

export function buildStockRows(stock: Stock[], rates: Map<string, number>): StockRow[] {
  return stock.map((s) => {
    const rate = rates.get(s.product_id) ?? 0;
    const coverageDays = rate > 0 ? s.available / rate : null;
    const fill =
      coverageDays !== null ? Math.min(1, coverageDays / 30) : Math.min(1, s.available / 25);
    return {
      productId: s.product_id,
      available: s.available,
      reserved: s.reserved ?? 0,
      dailyRate: rate,
      coverageDays,
      fill,
      level: stockLevel(s.available, coverageDays),
    };
  });
}

export function parseStockInput(
  raw: string,
): { ok: true; value: number } | { ok: false; error: string } {
  const text = raw.trim();
  if (text === "") return { ok: false, error: "Informe a quantidade." };
  if (!/^\d+$/.test(text)) return { ok: false, error: "Use só números inteiros, sem sinal." };
  const value = Number(text);
  if (value > 100_000) return { ok: false, error: "O máximo é 100.000 unidades." };
  return { ok: true, value };
}

export type AlertTone = "danger" | "warn" | "good";
export type MerchantTab = "visao-geral" | "pedidos" | "estoque" | "produtos" | "extrato";

export const MERCHANT_TABS: { id: MerchantTab; label: string; key: string }[] = [
  { id: "visao-geral", label: "Visão geral", key: "v" },
  { id: "pedidos", label: "Pedidos", key: "p" },
  { id: "estoque", label: "Estoque", key: "e" },
  { id: "produtos", label: "Produtos", key: "r" },
  { id: "extrato", label: "Extrato", key: "x" },
];

export const PERIODS = [7, 14, 30] as const;

export function parseTab(value: unknown): MerchantTab {
  return MERCHANT_TABS.find((t) => t.id === value)?.id ?? "visao-geral";
}

export function parsePeriod(value: unknown): (typeof PERIODS)[number] {
  return PERIODS.find((p) => p === value) ?? 30;
}

export interface MerchantAlert {
  id: string;
  tone: AlertTone;
  title: string;
  description: string;
  tab: MerchantTab;
  action: string;
}

export function plural(n: number, one: string, many: string): string {
  return n === 1 ? one : many;
}

export function buildAlerts(input: {
  stockRows: StockRow[];
  orders: MerchantOrder[];
  comparison: Comparison | null;
  now: number;
  days: number;
}): MerchantAlert[] {
  const alerts: MerchantAlert[] = [];
  const out = input.stockRows.filter((r) => r.level === "out").length;
  const low = input.stockRows.filter((r) => r.level === "critical").length;
  if (out > 0) {
    alerts.push({
      id: "stock-out",
      tone: "danger",
      title: `${out} ${plural(out, "produto esgotado", "produtos esgotados")}`,
      description:
        "Quem tentar comprar vai receber o aviso de indisponível. Reponha para voltar a vender.",
      tab: "estoque",
      action: "Repor estoque",
    });
  }
  if (low > 0) {
    alerts.push({
      id: "stock-low",
      tone: "warn",
      title: `${low} ${plural(low, "produto com estoque baixo", "produtos com estoque baixo")}`,
      description: `Restam ${LOW_STOCK} unidades ou menos, ou o ritmo de vendas esgota em poucos dias.`,
      tab: "estoque",
      action: "Ver estoque",
    });
  }
  const stale = input.orders.filter(
    (o) =>
      orderStatus(o.status) === "PENDING" &&
      input.now - new Date(o.created_at).getTime() > STALE_PENDING_MS,
  ).length;
  if (stale > 0) {
    alerts.push({
      id: "stale-pending",
      tone: "warn",
      title: `${stale} ${plural(stale, "pedido aguardando", "pedidos aguardando")} pagamento há mais de 5 minutos`,
      description:
        "O PIX ainda não caiu. Se não for pago a tempo, o pedido expira e o estoque volta.",
      tab: "pedidos",
      action: "Ver pedidos",
    });
  }
  const gross = input.comparison?.deltas.gross ?? null;
  if (gross !== null && input.comparison?.hasPrevious) {
    if (gross <= DROP_ALERT) {
      alerts.push({
        id: "sales-drop",
        tone: "danger",
        title: `Vendas ${formatPct(gross, 0).replace("-", "")} abaixo do período anterior`,
        description: `Os últimos ${input.days} dias vendem menos que os ${input.days} anteriores. Confira os pedidos cancelados.`,
        tab: "pedidos",
        action: "Investigar",
      });
    } else if (gross >= 0.2) {
      alerts.push({
        id: "sales-up",
        tone: "good",
        title: `Vendas ${formatPct(gross, 0)} acima do período anterior`,
        description:
          "Boa fase. Garanta estoque nos produtos mais vendidos para não perder pedidos.",
        tab: "estoque",
        action: "Conferir estoque",
      });
    }
  }
  const order = { danger: 0, warn: 1, good: 2 } as const;
  return alerts.sort((a, b) => order[a.tone] - order[b.tone]);
}

export type EntryTypeFilter = "ALL" | "CREDIT" | "DEBIT";

export function filterEntries(entries: LedgerEntry[], type: EntryTypeFilter): LedgerEntry[] {
  return type === "ALL" ? entries : entries.filter((e) => e.direction === type);
}

export interface EntryRow {
  entry: LedgerEntry;
  balance: number;
}

export function withRunningBalance(entries: LedgerEntry[]): EntryRow[] {
  const ordered = [...entries].sort((a, b) => a.created_at.localeCompare(b.created_at));
  let balance = 0;
  const rows = ordered.map((entry) => {
    balance += entry.direction === "CREDIT" ? entry.amount_cents : -entry.amount_cents;
    return { entry, balance };
  });
  return rows.reverse();
}

export interface DayGroup {
  day: string;
  rows: EntryRow[];
  net: number;
}

export function localDayKey(iso: string): string {
  const d = new Date(iso);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export function groupByDay(rows: EntryRow[]): DayGroup[] {
  const groups: DayGroup[] = [];
  for (const row of rows) {
    const day = localDayKey(row.entry.created_at);
    let group = groups.at(-1);
    if (!group || group.day !== day) {
      group = { day, rows: [], net: 0 };
      groups.push(group);
    }
    group.rows.push(row);
    group.net +=
      row.entry.direction === "CREDIT" ? row.entry.amount_cents : -row.entry.amount_cents;
  }
  return groups;
}

function csvCell(value: string): string {
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n;]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function entriesToCsv(rows: EntryRow[]): string {
  const header = ["Data", "Descrição", "Tipo", "Valor (R$)", "Saldo acumulado (R$)", "Pedido"];
  const money = (cents: number) => (cents / 100).toFixed(2).replace(".", ",");
  const lines = rows.map(({ entry, balance }) =>
    [
      entry.created_at,
      entry.description,
      entry.direction === "CREDIT" ? "Crédito" : "Débito",
      `${entry.direction === "CREDIT" ? "" : "-"}${money(entry.amount_cents)}`,
      money(balance),
      entry.order_id ?? "",
    ]
      .map(csvCell)
      .join(";"),
  );
  return `﻿${[header.join(";"), ...lines].join("\r\n")}`;
}

export function parseReais(raw: string): number | null {
  const text = raw.trim().replace(/^R\$\s*/i, "");
  let normalized: string;
  if (/^\d{1,3}(\.\d{3})*,\d{1,2}$|^\d+,\d{1,2}$/.test(text)) {
    normalized = text.replace(/\./g, "").replace(",", ".");
  } else if (/^\d+\.\d{1,2}$/.test(text)) {
    normalized = text;
  } else if (/^\d{1,3}(\.\d{3})+$/.test(text)) {
    normalized = text.replace(/\./g, "");
  } else if (/^\d+$/.test(text)) {
    normalized = text;
  } else {
    return null;
  }
  return Math.round(Number(normalized) * 100);
}

export function centsToInput(cents: number): string {
  return (cents / 100).toFixed(2).replace(".", ",");
}
