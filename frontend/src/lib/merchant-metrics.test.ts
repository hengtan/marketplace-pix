import { describe, expect, it } from "vitest";
import type { MerchantOrder } from "@/api/merchant";
import type { LedgerEntry } from "@/api/schemas";
import {
  bestDay,
  bestWeekday,
  buildAlerts,
  buildStockRows,
  calendarGrid,
  centsToInput,
  comparePeriods,
  countByStatus,
  type Daily,
  dailySalesRate,
  detectOrderChanges,
  entriesToCsv,
  filterEntries,
  filterOrders,
  formatPct,
  groupByDay,
  heatLevel,
  movingAverage,
  paginate,
  parseReais,
  parseStockInput,
  pctChange,
  snapshotStatuses,
  splitPeriods,
  stockLevel,
  weekdayAggregate,
  withRunningBalance,
} from "./merchant-metrics";

function day(date: string, gross: number, orders: number): Daily {
  return { date, gross_cents: gross, net_cents: Math.round(gross * 0.9), orders };
}

function series(n: number, value: (i: number) => number): Daily[] {
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(Date.UTC(2026, 9, 1 + i)).toISOString().slice(0, 10);
    const gross = value(i);
    return day(d, gross, gross > 0 ? 2 : 0);
  });
}

function order(
  id: string,
  status: string,
  createdAt: string,
  items: [string, number][] = [["p1", 1]],
): MerchantOrder {
  return {
    id,
    status,
    currency: "BRL",
    created_at: createdAt,
    customer_name: "Maria Souza",
    subtotal_cents: 1000,
    items: items.map(([product_id, quantity]) => ({
      product_id,
      merchant_id: "m1",
      quantity,
      unit_price_cents: 1000,
    })),
  };
}

describe("pctChange", () => {
  it("computes the relative change", () => {
    expect(pctChange(150, 100)).toBeCloseTo(0.5);
    expect(pctChange(50, 100)).toBeCloseTo(-0.5);
  });
  it("handles a zero baseline without dividing by zero", () => {
    expect(pctChange(0, 0)).toBe(0);
    expect(pctChange(10, 0)).toBeNull();
  });
});

describe("formatPct", () => {
  it("adds the sign and uses the pt-BR decimal comma", () => {
    expect(formatPct(0.123)).toBe("+12,3%");
    expect(formatPct(-0.05)).toBe("-5,0%");
    expect(formatPct(0)).toBe("0,0%");
  });
});

describe("comparePeriods", () => {
  it("splits a doubled window in two halves and compares them", () => {
    const daily = series(14, (i) => (i < 7 ? 1000 : 1500));
    const cmp = comparePeriods(daily, 7);
    expect(cmp.current.gross).toBe(7 * 1500);
    expect(cmp.previous.gross).toBe(7 * 1000);
    expect(cmp.deltas.gross).toBeCloseTo(0.5);
    expect(cmp.hasPrevious).toBe(true);
  });
  it("reports no baseline when the previous half is missing or empty", () => {
    expect(
      comparePeriods(
        series(7, () => 1000),
        7,
      ).hasPrevious,
    ).toBe(false);
    const empty = comparePeriods(
      series(14, (i) => (i < 7 ? 0 : 900)),
      7,
    );
    expect(empty.hasPrevious).toBe(false);
    expect(empty.deltas.gross).toBeNull();
  });
  it("computes ticket and effective fee rate", () => {
    const cmp = comparePeriods(
      series(14, () => 2000),
      7,
    );
    expect(cmp.current.ticket).toBe(1000);
    expect(cmp.current.feeRate).toBeCloseTo(0.1);
    expect(cmp.deltas.feeRate).toBeCloseTo(0);
  });
  it("splitPeriods keeps chronological order even if the API shuffles it", () => {
    const shuffled = [...series(6, (i) => i * 100)].reverse();
    const { current, previous } = splitPeriods(shuffled, 3);
    expect(current.map((d) => d.gross_cents)).toEqual([300, 400, 500]);
    expect(previous.map((d) => d.gross_cents)).toEqual([0, 100, 200]);
  });
});

describe("movingAverage", () => {
  it("averages a trailing window and shrinks it at the start", () => {
    expect(movingAverage([10, 20, 30, 40], 3)).toEqual([10, 15, 20, 30]);
  });
  it("returns the series itself for window 1", () => {
    expect(movingAverage([5, 7], 1)).toEqual([5, 7]);
  });
});

describe("weekday aggregation", () => {
  it("groups by weekday (2026-11-01 is a Sunday)", () => {
    const daily = [
      day("2026-11-01", 1000, 1),
      day("2026-11-08", 3000, 3),
      day("2026-11-02", 500, 1),
    ];
    const stats = weekdayAggregate(daily);
    expect(stats[0]).toMatchObject({
      weekday: 0,
      gross: 4000,
      orders: 4,
      occurrences: 2,
      avgGross: 2000,
    });
    expect(stats[1]?.avgGross).toBe(500);
    expect(bestWeekday(stats)?.weekday).toBe(0);
  });
  it("finds the best single day and ignores empty periods", () => {
    expect(bestDay([day("2026-11-01", 10, 1), day("2026-11-02", 90, 1)])?.date).toBe("2026-11-02");
    expect(bestDay([day("2026-11-01", 0, 0)])).toBeNull();
    expect(bestWeekday(weekdayAggregate([]))).toBeNull();
  });
  it("lays days out in a Sunday-first calendar padded with blanks", () => {
    const grid = calendarGrid([day("2026-11-04", 1, 1), day("2026-11-05", 1, 1)]);
    expect(grid).toHaveLength(1);
    expect(grid[0]?.slice(0, 3)).toEqual([null, null, null]);
    expect(grid[0]?.[3]?.date).toBe("2026-11-04");
    expect(grid[0]).toHaveLength(7);
  });
  it("maps values to heat levels", () => {
    expect(heatLevel(0, 100)).toBe(0);
    expect(heatLevel(1, 100)).toBe(1);
    expect(heatLevel(100, 100)).toBe(4);
  });
});

describe("filterOrders and pagination", () => {
  const now = new Date("2026-11-11T12:00:00Z").getTime();
  const orders = [
    order("a1", "PAID", "2026-11-11T11:00:00Z", [["p1", 2]]),
    order("b2", "PENDING", "2026-11-11T11:55:00Z", [["p2", 1]]),
    { ...order("c3", "CANCELLED", "2026-10-01T11:00:00Z"), customer_name: "João Pereira" },
  ];
  it("filters by status", () => {
    expect(filterOrders(orders, { status: "PAID", query: "" }).map((o) => o.id)).toEqual(["a1"]);
    expect(filterOrders(orders, { status: "ALL", query: "" })).toHaveLength(3);
  });
  it("searches customer, id and product name ignoring accents and case", () => {
    expect(filterOrders(orders, { status: "ALL", query: "joao" }).map((o) => o.id)).toEqual(["c3"]);
    expect(filterOrders(orders, { status: "ALL", query: "B2" }).map((o) => o.id)).toEqual(["b2"]);
    const names = { p2: "Mochila de Trilha" };
    expect(
      filterOrders(orders, { status: "ALL", query: "mochila", names }).map((o) => o.id),
    ).toEqual(["b2"]);
  });
  it("filters by period", () => {
    const since = now - 7 * 86_400_000;
    expect(filterOrders(orders, { status: "ALL", query: "", sinceMs: since })).toHaveLength(2);
  });
  it("counts by status and paginates safely", () => {
    expect(countByStatus(orders)).toEqual({ ALL: 3, PENDING: 1, PAID: 1, CANCELLED: 1 });
    expect(paginate([1, 2, 3, 4, 5], 2, 2)).toEqual({ items: [3, 4], page: 2, pages: 3 });
    expect(paginate([1, 2, 3], 9, 2).page).toBe(2);
    expect(paginate([], 1, 5)).toEqual({ items: [], page: 1, pages: 1 });
  });
  it("treats unknown statuses as cancelled", () => {
    expect(countByStatus([order("x", "REFUNDED", "2026-11-11T11:00:00Z")]).CANCELLED).toBe(1);
  });
});

describe("detectOrderChanges", () => {
  const o1 = order("1", "PENDING", "2026-11-11T10:00:00Z");
  it("reports nothing on the first load", () => {
    expect(detectOrderChanges(null, [o1])).toEqual({ created: [], paid: [] });
  });
  it("detects a new order, a new paid order and a pending order that got paid", () => {
    const known = snapshotStatuses([o1]);
    const paidNow = { ...o1, status: "PAID" };
    const fresh = order("2", "PENDING", "2026-11-11T10:05:00Z");
    const freshPaid = order("3", "PAID", "2026-11-11T10:06:00Z");
    const changes = detectOrderChanges(known, [paidNow, fresh, freshPaid]);
    expect(changes.paid.map((o) => o.id)).toEqual(["1", "3"]);
    expect(changes.created.map((o) => o.id)).toEqual(["2"]);
  });
  it("does not repeat when nothing changed", () => {
    expect(detectOrderChanges(snapshotStatuses([o1]), [o1])).toEqual({ created: [], paid: [] });
  });
});

describe("stock", () => {
  const now = new Date("2026-11-11T12:00:00Z").getTime();
  it("derives a daily sales rate from paid orders in the window only", () => {
    const orders = [
      order("1", "PAID", "2026-11-10T10:00:00Z", [["p1", 14]]),
      order("2", "CANCELLED", "2026-11-10T10:00:00Z", [["p1", 50]]),
      order("3", "PAID", "2026-09-01T10:00:00Z", [["p1", 50]]),
    ];
    expect(dailySalesRate(orders, now).get("p1")).toBeCloseTo(1);
  });
  it("classifies levels by quantity and coverage", () => {
    expect(stockLevel(0, null)).toBe("out");
    expect(stockLevel(3, null)).toBe("critical");
    expect(stockLevel(20, 2)).toBe("critical");
    expect(stockLevel(20, 5)).toBe("attention");
    expect(stockLevel(20, 12)).toBe("healthy");
    expect(stockLevel(25, null)).toBe("healthy");
  });
  it("builds rows with coverage and a bounded fill", () => {
    const rows = buildStockRows(
      [
        { product_id: "p1", available: 10, reserved: 2 },
        { product_id: "p2", available: 40 },
      ],
      new Map([["p1", 2]]),
    );
    expect(rows[0]).toMatchObject({ coverageDays: 5, reserved: 2, level: "attention" });
    expect(rows[0]?.fill).toBeCloseTo(5 / 30);
    expect(rows[1]).toMatchObject({ coverageDays: null, reserved: 0, fill: 1 });
  });
  it("validates inline stock input", () => {
    expect(parseStockInput("12")).toEqual({ ok: true, value: 12 });
    expect(parseStockInput(" 0 ")).toEqual({ ok: true, value: 0 });
    expect(parseStockInput("").ok).toBe(false);
    expect(parseStockInput("-3").ok).toBe(false);
    expect(parseStockInput("2,5").ok).toBe(false);
    expect(parseStockInput("100001").ok).toBe(false);
  });
});

describe("alerts", () => {
  const now = new Date("2026-11-11T12:00:00Z").getTime();
  const rows = buildStockRows(
    [
      { product_id: "a", available: 0 },
      { product_id: "b", available: 3 },
      { product_id: "c", available: 30 },
    ],
    new Map(),
  );
  it("raises stock, stale pending and sales drop alerts, most urgent first", () => {
    const drop = comparePeriods(
      series(14, (i) => (i < 7 ? 2000 : 1000)),
      7,
    );
    const alerts = buildAlerts({
      stockRows: rows,
      orders: [
        order("1", "PENDING", "2026-11-11T11:50:00Z"),
        order("2", "PENDING", "2026-11-11T11:59:00Z"),
      ],
      comparison: drop,
      now,
      days: 7,
    });
    expect(alerts.map((a) => a.id)).toEqual([
      "stock-out",
      "sales-drop",
      "stock-low",
      "stale-pending",
    ]);
    expect(alerts.find((a) => a.id === "stale-pending")?.title).toContain("1 pedido aguardando");
    expect(alerts.find((a) => a.id === "stale-pending")?.tab).toBe("pedidos");
    expect(alerts.find((a) => a.id === "stock-low")?.tab).toBe("estoque");
  });
  it("celebrates growth and stays quiet when all is fine", () => {
    const up = comparePeriods(
      series(14, (i) => (i < 7 ? 1000 : 1500)),
      7,
    );
    expect(buildAlerts({ stockRows: [], orders: [], comparison: up, now, days: 7 })[0]?.tone).toBe(
      "good",
    );
    const flat = comparePeriods(
      series(14, () => 1000),
      7,
    );
    expect(buildAlerts({ stockRows: [], orders: [], comparison: flat, now, days: 7 })).toEqual([]);
  });
  it("does not flag a drop without a baseline", () => {
    const none = comparePeriods(
      series(7, () => 100),
      7,
    );
    expect(buildAlerts({ stockRows: [], orders: [], comparison: none, now, days: 7 })).toEqual([]);
  });
});

describe("statement", () => {
  const entry = (
    id: string,
    direction: "CREDIT" | "DEBIT",
    cents: number,
    at: string,
    description = "Venda",
  ): LedgerEntry => ({
    id,
    transaction_id: `t${id}`,
    direction,
    amount_cents: cents,
    description,
    order_id: null,
    created_at: at,
  });
  const entries = [
    entry("3", "DEBIT", 200, "2026-11-11T12:00:00"),
    entry("2", "CREDIT", 1000, "2026-11-11T09:00:00"),
    entry("1", "CREDIT", 500, "2026-11-10T09:00:00"),
  ];
  it("computes the running balance from the oldest entry, newest first", () => {
    const rows = withRunningBalance(entries);
    expect(rows.map((r) => r.balance)).toEqual([1300, 1500, 500]);
  });
  it("filters by type and groups by local day with the net of each day", () => {
    expect(filterEntries(entries, "DEBIT")).toHaveLength(1);
    expect(filterEntries(entries, "ALL")).toHaveLength(3);
    const groups = groupByDay(withRunningBalance(entries));
    expect(groups.map((g) => [g.day, g.rows.length, g.net])).toEqual([
      ["2026-11-11", 2, 800],
      ["2026-11-10", 1, 500],
    ]);
  });
  it("exports CSV with BOM, semicolons, quoting and formula injection guard", () => {
    const rows = withRunningBalance([
      entry("1", "CREDIT", 12345, "2026-11-10T09:00:00", 'Venda "especial"; teste'),
      entry("2", "DEBIT", 99, "2026-11-10T10:00:00", "=HYPERLINK(1)"),
    ]);
    const csv = entriesToCsv(rows);
    expect(csv.startsWith("﻿Data;Descrição;Tipo")).toBe(true);
    expect(csv).toContain('"Venda ""especial""; teste"');
    expect(csv).toContain("123,45");
    expect(csv).toContain("-0,99");
    expect(csv).toContain("'=HYPERLINK(1)");
    expect(csv.split("\r\n")).toHaveLength(3);
  });
});

describe("money input", () => {
  it("parses reais in pt-BR formats", () => {
    expect(parseReais("49,90")).toBe(4990);
    expect(parseReais("1.299,00")).toBe(129900);
    expect(parseReais("R$ 10")).toBe(1000);
    expect(parseReais("49.9")).toBe(4990);
    expect(parseReais("1.234")).toBe(123400);
  });
  it("rejects garbage", () => {
    expect(parseReais("")).toBeNull();
    expect(parseReais("abc")).toBeNull();
    expect(parseReais("-5")).toBeNull();
    expect(parseReais("1,234")).toBeNull();
  });
  it("formats cents for the input", () => {
    expect(centsToInput(4990)).toBe("49,90");
  });
});
