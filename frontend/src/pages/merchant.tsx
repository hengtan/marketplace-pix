import { ChevronLeft, ChevronRight, CircleAlert, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MerchantSummary } from "@/api/schemas";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useMerchantEntries, useMerchantSummary, useReconciliation } from "@/hooks/queries";
import { usePageTitle } from "@/hooks/utils";
import { formatDateTime, formatMoney, formatShortDay } from "@/lib/format";
import { SEED_MERCHANTS } from "@/lib/merchants";
import { cn } from "@/lib/utils";

const RANGES = [7, 14, 30] as const;

function compactMoney(cents: number): string {
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", notation: "compact", maximumFractionDigits: 1 }).format(cents / 100);
}

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "primary" }) {
  return (
    <div
      className={cn(
        "rounded-lg border p-5",
        tone === "primary" ? "border-transparent bg-primary text-primary-foreground" : "border-border bg-surface",
      )}
    >
      <dt className={cn("text-sm", tone === "primary" ? "opacity-80" : "text-muted")}>{label}</dt>
      <dd className="tabular mt-2 font-display text-3xl font-bold tracking-tight">{value}</dd>
      {hint && <p className={cn("mt-1 text-xs", tone === "primary" ? "opacity-75" : "text-muted")}>{hint}</p>}
    </div>
  );
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { value: number; name: string; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-surface px-3 py-2 text-sm shadow-lift">
      <p className="mb-1 font-medium">{label}</p>
      {payload.map((p) => (
        <p key={p.name} className="tabular flex items-center gap-2 text-muted">
          <span className="size-2 rounded-full" style={{ background: p.color }} />
          {p.name}: <span className="font-medium text-foreground">{formatMoney(p.value)}</span>
        </p>
      ))}
    </div>
  );
}

function SalesChart({ summary }: { summary: MerchantSummary }) {
  const data = summary.daily.map((d) => ({
    day: formatShortDay(d.date),
    Bruto: d.gross_cents,
    Líquido: d.net_cents,
  }));
  const last = summary.daily.at(-1);
  return (
    <figure
      className="rounded-lg border border-border bg-surface p-4 sm:p-6"
      aria-label={`Gráfico de vendas diárias dos últimos ${summary.daily.length} dias`}
    >
      <figcaption className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <span className="font-display text-xl font-semibold">Vendas por dia</span>
        <span className="flex items-center gap-4 text-sm text-muted">
          <span className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-primary" /> Bruto</span>
          <span className="flex items-center gap-2"><span className="size-2.5 rounded-full bg-pix" /> Líquido</span>
        </span>
      </figcaption>
      <div className="h-72 w-full" role="img" aria-label={last ? `Último dia: ${formatMoney(last.gross_cents)} brutos em ${last.orders} pedidos` : "Sem dados"}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="g-gross" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--primary)" stopOpacity={0.35} />
                <stop offset="100%" stopColor="var(--primary)" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="g-net" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--pix)" stopOpacity={0.35} />
                <stop offset="100%" stopColor="var(--pix)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 4" />
            <XAxis dataKey="day" tickLine={false} axisLine={false} tick={{ fill: "var(--muted)", fontSize: 12 }} minTickGap={24} />
            <YAxis tickLine={false} axisLine={false} width={64} tick={{ fill: "var(--muted)", fontSize: 12 }} tickFormatter={compactMoney} />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--muted)", strokeDasharray: "3 3" }} />
            <Area type="monotone" dataKey="Bruto" stroke="var(--primary)" strokeWidth={2.5} fill="url(#g-gross)" isAnimationActive={false} />
            <Area type="monotone" dataKey="Líquido" stroke="var(--pix)" strokeWidth={2.5} fill="url(#g-net)" isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

function Statement({ merchantId }: { merchantId: string }) {
  const [page, setPage] = useState(1);
  const { data, isPending, isError, refetch } = useMerchantEntries(merchantId, page);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <section aria-labelledby="extrato" className="rounded-lg border border-border bg-surface p-4 sm:p-6">
      <h2 id="extrato" className="font-display text-xl font-semibold">
        Extrato
      </h2>
      {isError ? (
        <ErrorState onRetry={() => refetch()} title="Não foi possível carregar o extrato" />
      ) : isPending ? (
        <div className="mt-4 grid gap-2" aria-busy>
          {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-10 w-full" />)}
        </div>
      ) : data.items.length === 0 ? (
        <p className="py-8 text-center text-muted">Ainda não há lançamentos para este lojista.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-left text-sm">
            <caption className="sr-only">Lançamentos da conta do lojista</caption>
            <thead className="text-muted">
              <tr className="border-b border-border">
                <th scope="col" className="py-2 pr-4 font-medium">Data</th>
                <th scope="col" className="py-2 pr-4 font-medium">Descrição</th>
                <th scope="col" className="py-2 pr-4 font-medium">Tipo</th>
                <th scope="col" className="py-2 text-right font-medium">Valor</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((e) => (
                <tr key={e.id} className="border-b border-border/60 last:border-0">
                  <td className="tabular py-3 pr-4 whitespace-nowrap text-muted">{formatDateTime(e.created_at)}</td>
                  <td className="py-3 pr-4">{e.description}</td>
                  <td className="py-3 pr-4">
                    <Badge tone={e.direction === "CREDIT" ? "pix" : "neutral"}>{e.direction === "CREDIT" ? "Crédito" : "Débito"}</Badge>
                  </td>
                  <td className="tabular py-3 text-right font-medium">
                    {e.direction === "CREDIT" ? "+" : "-"}
                    {formatMoney(e.amount_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <nav aria-label="Paginação do extrato" className="mt-4 flex items-center justify-end gap-3">
          <Button variant="outline" size="icon" onClick={() => setPage((p) => p - 1)} disabled={page <= 1} aria-label="Página anterior">
            <ChevronLeft />
          </Button>
          <span className="tabular text-sm text-muted">{page} de {pages}</span>
          <Button variant="outline" size="icon" onClick={() => setPage((p) => p + 1)} disabled={page >= pages} aria-label="Próxima página">
            <ChevronRight />
          </Button>
        </nav>
      )}
    </section>
  );
}

function ReconciliationSeal() {
  const { data, isPending, isError } = useReconciliation();
  if (isPending) return <Skeleton className="h-9 w-56 rounded-full" />;
  if (isError || !data) return <Badge tone="warn"><CircleAlert className="size-3.5" /> Conciliação indisponível</Badge>;
  return data.balanced ? (
    <Badge tone="pix" className="py-2 text-sm" title={`Débitos e créditos somam ${formatMoney(data.total_credits_cents)}`}>
      <ShieldCheck className="size-4" /> Livro-razão conciliado, {data.transactions_count} lançamentos
    </Badge>
  ) : (
    <Badge tone="danger" className="py-2 text-sm">
      <CircleAlert className="size-4" /> Divergência no livro-razão
    </Badge>
  );
}

export default function MerchantPage() {
  usePageTitle("Painel do lojista");
  const [merchantId, setMerchantId] = useState(SEED_MERCHANTS[0]?.id ?? "");
  const [days, setDays] = useState<number>(30);
  const summary = useMerchantSummary(merchantId, days);
  const merchant = SEED_MERCHANTS.find((m) => m.id === merchantId);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-4xl font-bold sm:text-5xl">Painel do lojista</h1>
          <p className="mt-2 text-muted">Vendas, taxas e saldo direto do livro-razão.</p>
        </div>
        <ReconciliationSeal />
      </div>

      <div className="mt-8 flex flex-wrap items-center justify-between gap-4">
        <div role="radiogroup" aria-label="Lojista" className="flex flex-wrap gap-2">
          {SEED_MERCHANTS.map((m) => {
            const active = m.id === merchantId;
            return (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => setMerchantId(m.id)}
                className={cn(
                  "h-11 rounded-full border px-5 text-sm font-medium transition-colors",
                  active ? "border-foreground bg-foreground text-background" : "border-border bg-surface hover:border-primary",
                )}
              >
                {m.name}
              </button>
            );
          })}
        </div>
        <div role="radiogroup" aria-label="Período" className="flex gap-1 rounded-full bg-surface-2 p-1">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              role="radio"
              aria-checked={days === r}
              onClick={() => setDays(r)}
              className={cn(
                "h-9 rounded-full px-4 text-sm font-medium transition-colors",
                days === r ? "bg-surface shadow-soft" : "text-muted hover:text-foreground",
              )}
            >
              {r} dias
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-6">
        {summary.isError ? (
          <ErrorState onRetry={() => summary.refetch()} message={summary.error.message} title="Não foi possível carregar o resumo" />
        ) : summary.isPending ? (
          <div aria-busy className="grid gap-6">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-28 rounded-lg" />)}
            </div>
            <Skeleton className="h-80 rounded-lg" />
          </div>
        ) : (
          <>
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.3fr_repeat(4,1fr)]" aria-label={`Resumo de ${merchant?.name ?? "lojista"}`}>
              <Kpi tone="primary" label="Saldo a receber" value={formatMoney(summary.data.balance_cents)} hint={`${merchant?.name}, ${days} dias`} />
              <Kpi label="Vendas brutas" value={formatMoney(summary.data.gross_sales_cents)} />
              <Kpi label="Taxas da plataforma" value={formatMoney(summary.data.platform_fees_cents)} hint="10% sobre cada venda" />
              <Kpi label="Líquido" value={formatMoney(summary.data.net_sales_cents)} />
              <Kpi label="Pedidos" value={summary.data.orders_count.toLocaleString("pt-BR")} />
            </dl>
            <SalesChart summary={summary.data} />
          </>
        )}
        <Statement key={merchantId} merchantId={merchantId} />
      </div>
    </div>
  );
}
