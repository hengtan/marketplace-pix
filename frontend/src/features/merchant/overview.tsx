import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  Clock,
  PackageX,
  Sparkles,
  TrendingDown,
} from "lucide-react";
import { m } from "motion/react";
import { type CSSProperties, type ReactNode, Suspense, useMemo, useState } from "react";
import { AnimatedNumber } from "@/components/motion/animated-number";
import { Stagger, StaggerItem } from "@/components/motion/reveal";
import { ErrorState } from "@/components/states";
import { Skeleton } from "@/components/ui/misc";
import { useMerchantSummary } from "@/hooks/queries";
import { formatMoney, formatShortDay } from "@/lib/format";
import { formatCompactMoney } from "@/lib/format-merchant";
import { lazyReload } from "@/lib/lazy-reload";
import {
  bestDay,
  bestWeekday,
  buildAlerts,
  calendarGrid,
  comparePeriods,
  type Daily,
  heatLevel,
  type MerchantAlert,
  type MerchantTab,
  totalsOf,
  WEEKDAYS,
  WEEKDAYS_LONG,
  weekdayAggregate,
  weekdayOf,
} from "@/lib/merchant-metrics";
import { EASE } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useMerchant, useMerchantNav } from "./context";
import { useStockRows } from "./data";
import { Card, Delta, Sparkline } from "./ui";

const SalesChart = lazyReload(() =>
  import("@/features/merchant-chart").then((m) => ({ default: m.SalesChart })),
);
const OrdersChart = lazyReload(() =>
  import("@/features/merchant-chart").then((m) => ({ default: m.OrdersChart })),
);

function Kpi({
  label,
  value,
  format,
  hint,
  tone,
  series,
  delta,
}: {
  label: string;
  value: number;
  format: (n: number) => string;
  hint?: string;
  tone?: "primary";
  series: number[];
  delta?: ReactNode;
}) {
  const primary = tone === "primary";
  return (
    <StaggerItem
      className={cn(
        "relative overflow-hidden rounded-3xl p-5 transition-[transform,box-shadow] duration-300 ease-out hover:-translate-y-0.5",
        primary
          ? "bg-[linear-gradient(140deg,oklch(0.5_0.25_270),oklch(0.4_0.25_285))] text-white shadow-glow before:pointer-events-none before:absolute before:-top-10 before:-right-10 before:size-40 before:rounded-full before:bg-white/15 before:blur-2xl"
          : "panel hairline-top hover:shadow-lift",
      )}
    >
      <dt className={cn("relative text-sm font-medium", primary ? "opacity-85" : "text-muted")}>
        {label}
      </dt>
      <dd className="relative mt-2 font-display text-2xl font-bold tracking-tight whitespace-nowrap xl:text-[1.6rem]">
        <AnimatedNumber value={value} fromZero format={format} />
      </dd>
      {delta && <dd className="relative mt-2">{delta}</dd>}
      {hint && (
        <dd className={cn("relative mt-1 text-xs", primary ? "opacity-90" : "text-muted")}>
          {hint}
        </dd>
      )}
      <dd aria-hidden className="relative">
        <Sparkline values={series} tone={primary ? "primary" : "plain"} />
      </dd>
    </StaggerItem>
  );
}

const ALERT_STYLE = {
  danger: { icon: PackageX, ring: "border-danger/40 bg-danger-soft", ink: "text-danger" },
  warn: { icon: AlertTriangle, ring: "border-warn/40 bg-warn-soft", ink: "text-warn" },
  good: { icon: Sparkles, ring: "border-pix/50 bg-pix-soft", ink: "text-pix-ink" },
} as const;

function alertIcon(alert: MerchantAlert) {
  if (alert.id === "sales-drop") return TrendingDown;
  if (alert.id === "stale-pending") return Clock;
  return ALERT_STYLE[alert.tone].icon;
}

function AlertCards({
  alerts,
  onGo,
}: {
  alerts: MerchantAlert[];
  onGo: (tab: MerchantTab) => void;
}) {
  return (
    <section aria-label="Alertas" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {alerts.map((a, i) => {
        const style = ALERT_STYLE[a.tone];
        const Icon = alertIcon(a);
        return (
          <m.button
            key={a.id}
            type="button"
            onClick={() => onGo(a.tab)}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: i * 0.06, ease: EASE }}
            whileTap={{ scale: 0.985 }}
            className={cn(
              "group flex items-start gap-3 rounded-2xl border p-4 text-left transition-[transform,box-shadow] duration-300 hover:-translate-y-0.5 hover:shadow-lift",
              style.ring,
            )}
          >
            <span
              className={cn(
                "mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-surface",
                style.ink,
              )}
            >
              <Icon className="size-5" aria-hidden />
            </span>
            <span className="grid gap-1">
              <span className="font-semibold text-foreground">{a.title}</span>
              <span className="text-sm text-foreground/80">{a.description}</span>
              <span
                className={cn(
                  "mt-1 inline-flex items-center gap-1 text-sm font-semibold",
                  style.ink,
                )}
              >
                {a.action}
                <ArrowRight
                  className="size-4 transition-transform group-hover:translate-x-1"
                  aria-hidden
                />
              </span>
            </span>
          </m.button>
        );
      })}
    </section>
  );
}

const HEAT = ["transparent", "16%", "30%", "52%", "100%"] as const;

function heatStyle(level: number): CSSProperties {
  return {
    backgroundColor:
      level === 0
        ? "var(--surface-2)"
        : `color-mix(in oklab, var(--primary) ${HEAT[level]}, var(--surface-2))`,
  };
}

function Heatmap({ daily }: { daily: Daily[] }) {
  const grid = useMemo(() => calendarGrid(daily), [daily]);
  const stats = useMemo(() => weekdayAggregate(daily), [daily]);
  const best = bestWeekday(stats);
  const top = bestDay(daily);
  const max = Math.max(0, ...daily.map((d) => d.gross_cents));
  const maxAvg = Math.max(1, ...stats.map((s) => s.avgGross));
  const [hover, setHover] = useState<Daily | null>(null);
  const shown = hover ?? top;

  return (
    <Card aria-labelledby="mapa-calor" className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="mapa-calor" className="font-display text-xl font-semibold">
            Vendas por dia da semana
          </h2>
          <p className="mt-1 text-sm text-muted">Quanto mais escuro, maior a venda bruta do dia.</p>
        </div>
        <span aria-hidden className="flex items-center gap-1.5 text-xs text-muted">
          menos
          {[0, 1, 2, 3, 4].map((l) => (
            <span key={l} className="size-4 rounded" style={heatStyle(l)} />
          ))}
          mais
        </span>
      </div>
      <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
        <div>
          <table className="w-full table-fixed border-separate border-spacing-1 text-center sm:border-spacing-1.5">
            <caption className="sr-only">Calendário de vendas brutas por dia do período</caption>
            <thead>
              <tr>
                {WEEKDAYS.map((w) => (
                  <th key={w} scope="col" className="pb-1 text-xs font-medium text-muted">
                    {w}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.map((row, ri) => (
                <tr key={row.find((c) => c)?.date ?? ri}>
                  {row.map((cell, ci) => {
                    if (!cell) return <td key={`${ri}-${ci}`} aria-hidden />;
                    const level = heatLevel(cell.gross_cents, max);
                    const label = `${WEEKDAYS_LONG[weekdayOf(cell.date)]}, ${formatShortDay(cell.date)}: ${formatMoney(cell.gross_cents)} em ${cell.orders} ${cell.orders === 1 ? "pedido" : "pedidos"}`;
                    return (
                      <td
                        key={cell.date}
                        title={label}
                        onPointerEnter={() => setHover(cell)}
                        onPointerLeave={() => setHover(null)}
                        style={heatStyle(level)}
                        className={cn(
                          "tabular h-9 rounded-lg sm:h-11 text-xs font-medium transition-transform duration-200 hover:scale-110 sm:text-sm",
                          level === 4 ? "text-primary-foreground" : "text-foreground",
                        )}
                      >
                        <span aria-hidden>{Number(cell.date.slice(8))}</span>
                        <span className="sr-only">{label}</span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="grid content-start gap-4">
          <div>
            <h3 className="text-sm font-medium text-muted">Média por dia da semana</h3>
            <ul
              className="mt-3 grid grid-cols-7 items-end gap-2"
              aria-label="Média de vendas por dia da semana"
            >
              {stats.map((s) => {
                const isBest = best?.weekday === s.weekday;
                return (
                  <li key={s.weekday} className="grid justify-items-center gap-1.5">
                    <span className="tabular text-[0.7rem] text-muted">
                      {s.occurrences > 0 ? formatCompactMoney(s.avgGross) : "-"}
                    </span>
                    <span className="flex h-20 w-full items-end rounded-lg bg-surface-2">
                      <m.span
                        className={cn(
                          "w-full origin-bottom rounded-lg",
                          isBest ? "bg-primary" : "bg-primary/45",
                        )}
                        style={{ height: `${Math.max(4, (s.avgGross / maxAvg) * 100)}%` }}
                        initial={{ scaleY: 0 }}
                        animate={{ scaleY: 1 }}
                        transition={{ duration: 0.8, ease: EASE }}
                      />
                    </span>
                    <span
                      className={cn(
                        "text-xs",
                        isBest ? "font-semibold text-foreground" : "text-muted",
                      )}
                    >
                      {WEEKDAYS[s.weekday]}
                    </span>
                    <span className="sr-only">
                      {WEEKDAYS_LONG[s.weekday]}: média de {formatMoney(s.avgGross)} por dia
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
          <div className="rounded-2xl bg-primary-soft p-4" aria-live="polite">
            <p className="flex items-center gap-2 text-sm font-medium text-primary">
              <CalendarDays className="size-4" aria-hidden />
              {hover ? "Dia selecionado" : "Melhor dia"}
            </p>
            {shown ? (
              <>
                <p className="mt-1 font-display text-xl font-semibold first-letter:uppercase">
                  {WEEKDAYS_LONG[weekdayOf(shown.date)]}, {formatShortDay(shown.date)}
                </p>
                <p className="tabular text-sm text-foreground/80">
                  {formatMoney(shown.gross_cents)} em {shown.orders}{" "}
                  {shown.orders === 1 ? "pedido" : "pedidos"}
                </p>
              </>
            ) : (
              <p className="mt-1 text-sm text-foreground/80">Ainda não há vendas neste período.</p>
            )}
            {best && (
              <p className="mt-2 text-sm text-foreground/80">
                <span className="inline-block first-letter:uppercase">
                  {WEEKDAYS_LONG[best.weekday]}
                </span>{" "}
                é o dia mais forte, com média de {formatMoney(best.avgGross)}.
              </p>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

function OverviewSkeleton() {
  return (
    <div aria-busy className="grid gap-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-40 rounded-3xl" />
        ))}
      </div>
      <Skeleton className="h-96 rounded-3xl" />
    </div>
  );
}

export function Overview() {
  const { merchantId, merchantName, days } = useMerchant();
  const nav = useMerchantNav();
  const summary = useMerchantSummary(merchantId, days);
  const wide = useMerchantSummary(merchantId, days * 2);
  const { rows, orders } = useStockRows();
  const [average, setAverage] = useState(true);

  const comparison = useMemo(
    () => (wide.data ? comparePeriods(wide.data.daily, days) : null),
    [wide.data, days],
  );
  const alerts = useMemo(
    () =>
      buildAlerts({
        stockRows: rows ?? [],
        orders: orders.data?.items ?? [],
        comparison,
        now: Date.now(),
        days,
      }),
    [rows, orders.data, comparison, days],
  );

  if (summary.isError) {
    return (
      <ErrorState
        error={summary.error}
        onRetry={() => summary.refetch()}
        message={summary.error.message}
        title="Não foi possível carregar o resumo"
      />
    );
  }
  if (summary.isPending) return <OverviewSkeleton />;

  const data = summary.data;
  const daily = data.daily;
  const totals = totalsOf(daily);
  const gross = daily.map((d) => d.gross_cents);
  const net = daily.map((d) => d.net_cents);
  const count = daily.map((d) => d.orders);
  const ticket = daily.map((d) => (d.orders > 0 ? Math.round(d.gross_cents / d.orders) : 0));
  const feeRate = daily.map((d) =>
    d.gross_cents > 0 ? (d.gross_cents - d.net_cents) / d.gross_cents : 0,
  );
  const label = `vs ${days} dias anteriores`;
  const window = days <= 7 ? 3 : 7;
  const d = comparison?.deltas;

  return (
    <div className="grid gap-6">
      {alerts.length > 0 && <AlertCards alerts={alerts} onGo={nav.go} />}

      <Stagger
        as="dl"
        inView={false}
        step={0.06}
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6"
        aria-label={`Resumo de ${merchantName}`}
      >
        <Kpi
          tone="primary"
          label="Saldo a receber"
          value={data.balance_cents}
          format={(n) => formatMoney(Math.round(n))}
          hint={`${merchantName}, ${days} dias`}
          series={net}
        />
        <Kpi
          label="Vendas brutas"
          value={data.gross_sales_cents}
          format={(n) => formatMoney(Math.round(n))}
          series={gross}
          delta={<Delta value={d?.gross ?? null} label={label} />}
        />
        <Kpi
          label="Líquido"
          value={data.net_sales_cents}
          format={(n) => formatMoney(Math.round(n))}
          series={net}
          delta={<Delta value={d?.net ?? null} label={label} />}
        />
        <Kpi
          label="Pedidos"
          value={data.orders_count}
          format={(n) => Math.round(n).toLocaleString("pt-BR")}
          series={count}
          delta={<Delta value={d?.orders ?? null} label={label} />}
        />
        <Kpi
          label="Ticket médio"
          value={totals.ticket}
          format={(n) => formatMoney(Math.round(n))}
          series={ticket}
          delta={<Delta value={d?.ticket ?? null} label={label} />}
        />
        <Kpi
          label="Taxa efetiva"
          value={totals.feeRate * 10000}
          format={(n) => `${(n / 100).toFixed(1).replace(".", ",")}%`}
          hint={`${formatMoney(data.platform_fees_cents)} em taxas`}
          series={feeRate}
          delta={<Delta value={d?.feeRate ?? null} points invert label={label} />}
        />
      </Stagger>

      <div className="grid gap-6 xl:grid-cols-[1.7fr_1fr]">
        <Card aria-labelledby="vendas-dia">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 id="vendas-dia" className="font-display text-xl font-semibold">
              Vendas por dia
            </h2>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted">
              <span className="flex items-center gap-2">
                <span className="size-2.5 rounded-full bg-primary" /> Bruto
              </span>
              <span className="flex items-center gap-2">
                <span className="size-2.5 rounded-full bg-pix" /> Líquido
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={average}
                onClick={() => setAverage((v) => !v)}
                className="flex min-h-11 items-center gap-2 rounded-full px-1 text-foreground"
              >
                <span
                  className={cn(
                    "relative h-6 w-10 rounded-full transition-colors",
                    average ? "bg-sun" : "bg-surface-3",
                  )}
                >
                  <m.span
                    className="absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow-soft"
                    animate={{ x: average ? 16 : 0 }}
                    transition={{ type: "spring", stiffness: 500, damping: 32 }}
                  />
                </span>
                Média de {window} dias
              </button>
            </div>
          </div>
          <Suspense fallback={<Skeleton className="h-72 rounded-2xl sm:h-80" />}>
            <SalesChart daily={daily} showAverage={average} window={window} />
          </Suspense>
        </Card>
        <Card aria-labelledby="pedidos-dia">
          <h2 id="pedidos-dia" className="mb-4 font-display text-xl font-semibold">
            Pedidos por dia
          </h2>
          <Suspense fallback={<Skeleton className="h-72 rounded-2xl sm:h-80" />}>
            <OrdersChart daily={daily} total={data.orders_count} />
          </Suspense>
        </Card>
      </div>

      <Heatmap daily={daily} />
    </div>
  );
}
