import { useReducedMotion } from "motion/react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatMoney, formatShortDay } from "@/lib/format";
import { formatCompactMoney } from "@/lib/format-merchant";
import {
  type Daily,
  formatPct,
  movingAverage,
  pctChange,
  WEEKDAYS_LONG,
  weekdayOf,
} from "@/lib/merchant-metrics";

interface Point {
  date: string;
  day: string;
  Bruto: number;
  Líquido: number;
  Pedidos: number;
  Média: number;
  previous: number | null;
}

function toPoints(daily: Daily[], window: number): Point[] {
  const avg = movingAverage(
    daily.map((d) => d.gross_cents),
    window,
  );
  return daily.map((d, i) => ({
    date: d.date,
    day: formatShortDay(d.date),
    Bruto: d.gross_cents,
    Líquido: d.net_cents,
    Pedidos: d.orders,
    Média: avg[i] ?? 0,
    previous: i > 0 ? (daily[i - 1]?.gross_cents ?? null) : null,
  }));
}

function Row({
  color,
  label,
  value,
  strong,
}: {
  color?: string;
  label: string;
  value: string;
  strong?: boolean;
}) {
  return (
    <p className="tabular flex items-center justify-between gap-6 text-muted">
      <span className="flex items-center gap-2">
        {color && <span className="size-2.5 rounded-full" style={{ background: color }} />}
        {label}
      </span>
      <span className={strong ? "font-semibold text-foreground" : "text-foreground"}>{value}</span>
    </p>
  );
}

function SalesTooltip({
  active,
  payload,
  showAverage,
  window,
}: {
  active?: boolean;
  payload?: { payload: Point }[];
  showAverage: boolean;
  window: number;
}) {
  const p = payload?.[0]?.payload;
  if (!active || !p) return null;
  const fees = p.Bruto - p.Líquido;
  const ticket = p.Pedidos > 0 ? Math.round(p.Bruto / p.Pedidos) : 0;
  const change = p.previous !== null ? pctChange(p.Bruto, p.previous) : null;
  const weekday = WEEKDAYS_LONG[weekdayOf(p.date)] ?? "";
  return (
    <div className="glass min-w-56 rounded-2xl px-4 py-3 text-sm shadow-lift">
      <p className="mb-2 font-semibold">
        {p.day} <span className="font-normal text-muted">{weekday}</span>
      </p>
      <Row color="var(--primary)" label="Bruto" value={formatMoney(p.Bruto)} strong />
      <Row color="var(--pix)" label="Líquido" value={formatMoney(p.Líquido)} strong />
      <Row label="Taxas" value={formatMoney(fees)} />
      <Row label="Pedidos" value={String(p.Pedidos)} />
      <Row label="Ticket médio" value={ticket ? formatMoney(ticket) : "-"} />
      {showAverage && (
        <Row color="var(--sun)" label={`Média de ${window} dias`} value={formatMoney(p.Média)} />
      )}
      {change !== null && (
        <p className="mt-2 border-t border-border pt-2 text-xs text-muted">
          {formatPct(change)} em relação ao dia anterior
        </p>
      )}
    </div>
  );
}

function OrdersTooltip({ active, payload }: { active?: boolean; payload?: { payload: Point }[] }) {
  const p = payload?.[0]?.payload;
  if (!active || !p) return null;
  return (
    <div className="glass rounded-2xl px-4 py-3 text-sm shadow-lift">
      <p className="font-semibold">{p.day}</p>
      <p className="tabular text-muted">
        <span className="font-semibold text-foreground">{p.Pedidos}</span> pedidos
      </p>
    </div>
  );
}

const axis = { fill: "var(--muted)", fontSize: 12 };

export function SalesChart({
  daily,
  showAverage,
  window,
}: {
  daily: Daily[];
  showAverage: boolean;
  window: number;
}) {
  const reduce = useReducedMotion();
  const data = toPoints(daily, window);
  const last = daily.at(-1);
  return (
    <div
      className="h-72 w-full sm:h-80"
      role="img"
      aria-label={
        last
          ? `Vendas diárias dos últimos ${daily.length} dias. Último dia: ${formatMoney(last.gross_cents)} brutos em ${last.orders} pedidos`
          : "Sem dados"
      }
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="g-gross" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.4} />
              <stop offset="100%" stopColor="var(--primary)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="g-net" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--pix)" stopOpacity={0.4} />
              <stop offset="100%" stopColor="var(--pix)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 5" />
          <XAxis dataKey="day" tickLine={false} axisLine={false} tick={axis} minTickGap={24} />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={76}
            tick={axis}
            tickFormatter={formatCompactMoney}
          />
          <Tooltip
            content={<SalesTooltip showAverage={showAverage} window={window} />}
            cursor={{ stroke: "var(--primary)", strokeOpacity: 0.4, strokeDasharray: "3 3" }}
          />
          <Area
            type="monotone"
            dataKey="Bruto"
            stroke="var(--primary)"
            strokeWidth={2.5}
            fill="url(#g-gross)"
            isAnimationActive={!reduce}
            animationDuration={1400}
            activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--surface)" }}
          />
          <Area
            type="monotone"
            dataKey="Líquido"
            stroke="var(--pix)"
            strokeWidth={2.5}
            fill="url(#g-net)"
            isAnimationActive={!reduce}
            animationDuration={1400}
            animationBegin={200}
            activeDot={{ r: 5, strokeWidth: 2, stroke: "var(--surface)" }}
          />
          {showAverage && (
            <Line
              type="monotone"
              dataKey="Média"
              stroke="var(--sun)"
              strokeWidth={2.5}
              strokeDasharray="6 5"
              dot={false}
              isAnimationActive={!reduce}
              animationDuration={900}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function OrdersChart({ daily, total }: { daily: Daily[]; total: number }) {
  const reduce = useReducedMotion();
  const data = toPoints(daily, 7);
  return (
    <div className="h-72 w-full sm:h-80" role="img" aria-label={`${total} pedidos no período`}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 0, left: -24, bottom: 0 }}>
          <defs>
            <linearGradient id="g-bar" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--sun)" />
              <stop offset="100%" stopColor="var(--primary)" />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 5" />
          <XAxis dataKey="day" tickLine={false} axisLine={false} tick={axis} minTickGap={28} />
          <YAxis tickLine={false} axisLine={false} tick={axis} allowDecimals={false} />
          <Tooltip
            content={<OrdersTooltip />}
            cursor={{ fill: "var(--surface-2)", opacity: 0.6 }}
          />
          <Bar
            dataKey="Pedidos"
            fill="url(#g-bar)"
            radius={[6, 6, 2, 2]}
            isAnimationActive={!reduce}
            animationDuration={1000}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
