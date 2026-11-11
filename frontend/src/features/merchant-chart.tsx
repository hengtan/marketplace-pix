import { useReducedMotion } from "motion/react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { MerchantSummary } from "@/api/schemas";
import { formatMoney, formatShortDay } from "@/lib/format";

function compactMoney(cents: number): string {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(cents / 100);
}

function MoneyTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number; name: string; color: string }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass rounded-2xl px-4 py-3 text-sm shadow-lift">
      <p className="mb-1.5 font-semibold">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="tabular flex items-center gap-2 text-muted">
          <span className="size-2.5 rounded-full" style={{ background: p.color }} />
          {p.name}: <span className="font-semibold text-foreground">{formatMoney(p.value)}</span>
        </p>
      ))}
    </div>
  );
}

function OrdersTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { value: number }[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass rounded-2xl px-4 py-3 text-sm shadow-lift">
      <p className="font-semibold">{label}</p>
      <p className="tabular text-muted">
        <span className="font-semibold text-foreground">{payload[0]?.value}</span> pedidos
      </p>
    </div>
  );
}

const axis = { fill: "var(--muted)", fontSize: 12 };

export function SalesChart({ summary }: { summary: MerchantSummary }) {
  const reduce = useReducedMotion();
  const data = summary.daily.map((d) => ({
    day: formatShortDay(d.date),
    Bruto: d.gross_cents,
    Líquido: d.net_cents,
    Pedidos: d.orders,
  }));
  const last = summary.daily.at(-1);
  return (
    <div className="grid gap-6 lg:grid-cols-[1.7fr_1fr]">
      <figure
        className="panel hairline-top rounded-3xl p-4 sm:p-6"
        aria-label={`Gráfico de vendas diárias dos últimos ${summary.daily.length} dias`}
      >
        <figcaption className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <span className="font-display text-xl font-semibold">Vendas por dia</span>
          <span className="flex items-center gap-4 text-sm text-muted">
            <span className="flex items-center gap-2">
              <span className="size-2.5 rounded-full bg-primary" /> Bruto
            </span>
            <span className="flex items-center gap-2">
              <span className="size-2.5 rounded-full bg-pix" /> Líquido
            </span>
          </span>
        </figcaption>
        <div
          className="h-72 w-full"
          role="img"
          aria-label={
            last
              ? `Último dia: ${formatMoney(last.gross_cents)} brutos em ${last.orders} pedidos`
              : "Sem dados"
          }
        >
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
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
                width={64}
                tick={axis}
                tickFormatter={compactMoney}
              />
              <Tooltip
                content={<MoneyTooltip />}
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
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </figure>

      <figure className="panel hairline-top rounded-3xl p-4 sm:p-6" aria-label="Pedidos por dia">
        <figcaption className="mb-4 font-display text-xl font-semibold">Pedidos por dia</figcaption>
        <div
          className="h-72 w-full"
          role="img"
          aria-label={`${summary.orders_count} pedidos no período`}
        >
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
      </figure>
    </div>
  );
}
