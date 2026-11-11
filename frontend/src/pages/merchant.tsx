import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, CircleAlert, ShieldCheck } from "lucide-react";
import { m, useReducedMotion } from "motion/react";
import { lazy, Suspense, useState } from "react";
import { AnimatedNumber } from "@/components/motion/animated-number";
import { Stagger, StaggerItem } from "@/components/motion/reveal";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useMerchantEntries, useMerchantSummary, useReconciliation } from "@/hooks/queries";
import { usePageTitle } from "@/hooks/utils";
import { formatDateTime, formatMoney } from "@/lib/format";
import { merchantScope, SEED_MERCHANTS } from "@/lib/merchants";
import { EASE, SPRING } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useAuth } from "@/store/auth";

const RANGES = [7, 14, 30] as const;

const SalesChart = lazy(() =>
  import("@/features/merchant-chart").then((m) => ({ default: m.SalesChart })),
);

function Sparkline({ values, tone }: { values: number[]; tone: "primary" | "pix" | "plain" }) {
  const reduce = useReducedMotion();
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values);
  const w = 120;
  const h = 36;
  const pts: [number, number][] = values.map((v, i) => [
    (i / (values.length - 1)) * w,
    h - 4 - ((v - min) / (max - min || 1)) * (h - 8),
  ]);
  const d = pts
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  const stroke =
    tone === "primary" ? "stroke-white" : tone === "pix" ? "stroke-pix" : "stroke-primary";
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="mt-3 h-9 w-full"
      aria-hidden
      preserveAspectRatio="none"
    >
      <m.path
        d={d}
        fill="none"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        className={stroke}
        initial={reduce ? false : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1.4, ease: EASE, delay: 0.3 }}
      />
    </svg>
  );
}

function Kpi({
  label,
  cents,
  count,
  hint,
  tone,
  series,
}: {
  label: string;
  cents?: number;
  count?: number;
  hint?: string;
  tone?: "primary";
  series: number[];
}) {
  const value = cents ?? count ?? 0;
  return (
    <StaggerItem
      className={cn(
        "relative overflow-hidden rounded-3xl p-5",
        tone === "primary"
          ? "bg-[linear-gradient(140deg,oklch(0.5_0.25_270),oklch(0.4_0.25_285))] text-white shadow-glow before:pointer-events-none before:absolute before:-top-10 before:-right-10 before:size-40 before:rounded-full before:bg-white/15 before:blur-2xl"
          : "panel hairline-top",
      )}
    >
      <dt
        className={cn(
          "relative text-sm font-medium",
          tone === "primary" ? "opacity-85" : "text-muted",
        )}
      >
        {label}
      </dt>
      <dd className="relative mt-2 font-display text-2xl font-bold tracking-tight whitespace-nowrap xl:text-[1.7rem]">
        <AnimatedNumber
          value={value}
          fromZero
          format={(n) =>
            cents !== undefined ? formatMoney(Math.round(n)) : Math.round(n).toLocaleString("pt-BR")
          }
        />
      </dd>
      {hint && (
        <dd
          className={cn("relative mt-1 text-xs", tone === "primary" ? "opacity-90" : "text-muted")}
        >
          {hint}
        </dd>
      )}
      <dd aria-hidden className="relative">
        <Sparkline values={series} tone={tone === "primary" ? "primary" : "plain"} />
      </dd>
    </StaggerItem>
  );
}

function Statement({ merchantId }: { merchantId: string }) {
  const [page, setPage] = useState(1);
  const { data, isPending, isError, error, refetch } = useMerchantEntries(merchantId, page);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <section aria-labelledby="extrato" className="panel hairline-top rounded-3xl p-4 sm:p-6">
      <h2 id="extrato" className="font-display text-xl font-semibold">
        Extrato
      </h2>
      {isError ? (
        <ErrorState
          error={error}
          onRetry={() => refetch()}
          title="Não foi possível carregar o extrato"
        />
      ) : isPending ? (
        <div className="mt-4 grid gap-2" aria-busy>
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full rounded-xl" />
          ))}
        </div>
      ) : data.items.length === 0 ? (
        <p className="py-8 text-center text-muted">Ainda não há lançamentos para este lojista.</p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-left text-sm">
            <caption className="sr-only">Lançamentos da conta do lojista</caption>
            <thead className="text-xs tracking-wide text-muted uppercase">
              <tr className="border-b border-border">
                <th scope="col" className="py-2 pr-4 font-medium">
                  Data
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  Descrição
                </th>
                <th scope="col" className="py-2 pr-4 font-medium">
                  Tipo
                </th>
                <th scope="col" className="py-2 text-right font-medium">
                  Valor
                </th>
              </tr>
            </thead>
            <tbody>
              <>
                {data.items.map((e, i) => (
                  <m.tr
                    key={e.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4, delay: i * 0.04, ease: EASE }}
                    className="border-b border-border/60 transition-colors last:border-0 hover:bg-primary-soft/40"
                  >
                    <td className="tabular py-3 pr-4 whitespace-nowrap text-muted">
                      {formatDateTime(e.created_at)}
                    </td>
                    <td className="py-3 pr-4">{e.description}</td>
                    <td className="py-3 pr-4">
                      <Badge tone={e.direction === "CREDIT" ? "pix" : "neutral"}>
                        {e.direction === "CREDIT" ? "Crédito" : "Débito"}
                      </Badge>
                    </td>
                    <td
                      className={cn(
                        "tabular py-3 text-right font-semibold",
                        e.direction === "CREDIT" && "text-pix-ink",
                      )}
                    >
                      {e.direction === "CREDIT" ? "+" : "-"}
                      {formatMoney(e.amount_cents)}
                    </td>
                  </m.tr>
                ))}
              </>
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <nav aria-label="Paginação do extrato" className="mt-4 flex items-center justify-end gap-3">
          <Button
            variant="outline"
            size="icon"
            onClick={() => setPage((p) => p - 1)}
            disabled={page <= 1}
            aria-label="Página anterior"
          >
            <ChevronLeft />
          </Button>
          <span className="tabular text-sm text-muted">
            {page} de {pages}
          </span>
          <Button
            variant="outline"
            size="icon"
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= pages}
            aria-label="Próxima página"
          >
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
  if (isError || !data)
    return (
      <Badge tone="warn">
        <CircleAlert className="size-3.5" /> Conciliação indisponível
      </Badge>
    );
  return data.balanced ? (
    <Badge
      tone="pix"
      className="py-2 text-sm"
      title={`Débitos e créditos somam ${formatMoney(data.total_credits_cents)}`}
    >
      <ShieldCheck className="size-4" /> Livro-razão conciliado, {data.transactions_count}{" "}
      lançamentos
    </Badge>
  ) : (
    <Badge tone="danger" className="py-2 text-sm">
      <CircleAlert className="size-4" /> Divergência no livro-razão
    </Badge>
  );
}

function Segmented<T extends string | number>({
  label,
  options,
  value,
  onChange,
  id,
  render,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  id: string;
  render: (v: T) => string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="glass flex flex-wrap gap-1 rounded-full p-1"
    >
      {options.map((o) => {
        const active = o === value;
        return (
          <button
            key={String(o)}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o)}
            className={cn(
              "relative h-10 rounded-full px-4 text-sm font-medium transition-colors",
              active ? "text-background" : "text-muted hover:text-foreground",
            )}
          >
            {active && (
              <m.span
                layoutId={id}
                className="absolute inset-0 rounded-full bg-foreground"
                transition={SPRING}
              />
            )}
            <span className="relative">{render(o)}</span>
          </button>
        );
      })}
    </div>
  );
}

function Forbidden() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <EmptyState
        art="lost"
        title="Área exclusiva para lojistas"
        description="Sua conta não tem o perfil de lojista. Entre com uma conta de lojista para ver vendas e saldo."
        action={
          <Button asChild>
            <Link to="/">Voltar para a loja</Link>
          </Button>
        }
      />
    </div>
  );
}

export default function MerchantPage() {
  usePageTitle("Painel do lojista");
  const user = useAuth((s) => s.user);
  const scope = merchantScope(user);
  const [merchantId, setMerchantId] = useState(scope.initial);
  const [days, setDays] = useState<number>(30);
  const summary = useMerchantSummary(merchantId, days);
  const merchant = SEED_MERCHANTS.find((m) => m.id === merchantId);
  if (!scope.allowed) return <Forbidden />;
  const gross = summary.data?.daily.map((d) => d.gross_cents) ?? [];
  const net = summary.data?.daily.map((d) => d.net_cents) ?? [];
  const orders = summary.data?.daily.map((d) => d.orders) ?? [];
  const fees = gross.map((g, i) => g - (net[i] ?? 0));

  return (
    <div className="relative isolate overflow-hidden">
      <div className="aurora opacity-60" aria-hidden>
        <i />
        <i />
        <i />
      </div>
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-12">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-title">
              Painel do <span className="serif text-primary">lojista</span>
            </h1>
            <p className="mt-2 text-muted">Vendas, taxas e saldo direto do livro-razão.</p>
          </div>
          {scope.canReconcile && <ReconciliationSeal />}
        </div>

        <div className="mt-8 flex flex-wrap items-center justify-between gap-4">
          <Segmented
            id="merchant-pill"
            label="Lojista"
            options={scope.ids}
            value={merchantId}
            onChange={setMerchantId}
            render={(id) => SEED_MERCHANTS.find((m) => m.id === id)?.name ?? id}
          />
          <Segmented
            id="range-pill"
            label="Período"
            options={RANGES}
            value={days as (typeof RANGES)[number]}
            onChange={setDays}
            render={(r) => `${r} dias`}
          />
        </div>

        <div className="mt-6 grid gap-6">
          {summary.isError ? (
            <ErrorState
              error={summary.error}
              onRetry={() => summary.refetch()}
              message={summary.error.message}
              title="Não foi possível carregar o resumo"
            />
          ) : summary.isPending ? (
            <div aria-busy className="grid gap-6">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                {Array.from({ length: 5 }, (_, i) => (
                  <Skeleton key={i} className="h-36 rounded-3xl" />
                ))}
              </div>
              <Skeleton className="h-80 rounded-3xl" />
            </div>
          ) : (
            <>
              <Stagger
                as="dl"
                inView={false}
                step={0.07}
                className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.3fr_repeat(4,1fr)]"
                aria-label={`Resumo de ${merchant?.name ?? "lojista"}`}
              >
                <Kpi
                  tone="primary"
                  label="Saldo a receber"
                  cents={summary.data.balance_cents}
                  hint={`${merchant?.name}, ${days} dias`}
                  series={net}
                />
                <Kpi label="Vendas brutas" cents={summary.data.gross_sales_cents} series={gross} />
                <Kpi
                  label="Taxas da plataforma"
                  cents={summary.data.platform_fees_cents}
                  hint="10% sobre cada venda"
                  series={fees}
                />
                <Kpi label="Líquido" cents={summary.data.net_sales_cents} series={net} />
                <Kpi label="Pedidos" count={summary.data.orders_count} series={orders} />
              </Stagger>
              <Suspense fallback={<Skeleton className="h-96 rounded-3xl" />}>
                <SalesChart summary={summary.data} />
              </Suspense>
            </>
          )}
          <Statement key={merchantId} merchantId={merchantId} />
        </div>
      </div>
    </div>
  );
}
