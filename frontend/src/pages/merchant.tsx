import { getRouteApi, Link } from "@tanstack/react-router";
import { CircleAlert, Keyboard, ShieldCheck } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { Suspense, useMemo, useState } from "react";
import { EmptyState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Skeleton } from "@/components/ui/misc";
import {
  type MerchantCtx,
  MerchantProvider,
  useMerchant,
  useMerchantNav,
} from "@/features/merchant/context";
import { useStockRows } from "@/features/merchant/data";
import { useLiveOrders } from "@/features/merchant/live";
import { TAB_VIEWS } from "@/features/merchant/registry";
import { ShortcutsHelp, useMerchantShortcuts } from "@/features/merchant/shortcuts";
import { panelId, TabBar, tabId } from "@/features/merchant/tab-bar";
import { Segmented } from "@/features/merchant/ui";
import { useOwnsStore } from "@/hooks/merchant";
import { useReconciliation } from "@/hooks/queries";
import { usePageTitle } from "@/hooks/utils";
import { formatMoney } from "@/lib/format";
import {
  type MerchantTab,
  orderStatus,
  PERIODS,
  parsePeriod,
  parseTab,
} from "@/lib/merchant-metrics";
import { merchantScope, SEED_MERCHANTS } from "@/lib/merchants";
import { EASE } from "@/lib/motion";
import { useAuth } from "@/store/auth";

const route = getRouteApi("/lojista");

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

const PERIOD_TABS: MerchantTab[] = ["visao-geral", "pedidos", "extrato"];

function Panel({ scopeIds }: { scopeIds: string[] }) {
  const ctx = useMerchant();
  const nav = useMerchantNav();
  const { rows, orders } = useStockRows();
  const fresh = useLiveOrders(orders.data?.items, nav.openOrder);
  const full = { ...ctx, fresh };
  const [helpOpen, setHelpOpen] = useState(false);
  useMerchantShortcuts(() => setHelpOpen(true));

  const badges = useMemo(() => {
    const pending = (orders.data?.items ?? []).filter(
      (o) => orderStatus(o.status) === "PENDING",
    ).length;
    const critical = (rows ?? []).filter((r) => r.level === "out" || r.level === "critical").length;
    return {
      pedidos: { count: pending, label: "aguardando pagamento", tone: "warn" as const },
      estoque: { count: critical, label: "em alerta", tone: "danger" as const },
    };
  }, [orders.data, rows]);

  const View = TAB_VIEWS[ctx.tab];

  return (
    <MerchantProvider value={full}>
      <div className="mt-8 flex flex-wrap items-center justify-between gap-4">
        <TabBar active={ctx.tab} onChange={nav.go} badges={badges} />
        <div className="flex flex-wrap items-center gap-3">
          {scopeIds.length > 1 && (
            <Segmented
              id="merchant-pill"
              label="Lojista"
              options={scopeIds}
              value={ctx.merchantId}
              onChange={nav.setStore}
              render={(id) => SEED_MERCHANTS.find((m) => m.id === id)?.name ?? id}
            />
          )}
          {PERIOD_TABS.includes(ctx.tab) && (
            <Segmented
              id="range-pill"
              label="Período"
              options={PERIODS}
              value={parsePeriod(ctx.days)}
              onChange={nav.setDays}
              render={(r) => `${r} dias`}
            />
          )}
        </div>
      </div>

      <div className="mt-6">
        <AnimatePresence mode="wait" initial={false}>
          <m.div
            key={ctx.tab}
            role="tabpanel"
            id={panelId(ctx.tab)}
            aria-labelledby={tabId(ctx.tab)}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.22, ease: EASE }}
          >
            <Suspense fallback={<Skeleton className="h-96 rounded-3xl" />}>
              <View />
            </Suspense>
          </m.div>
        </AnimatePresence>
      </div>
      <ShortcutsHelp open={helpOpen} onOpenChange={setHelpOpen} />
      <button
        type="button"
        onClick={() => setHelpOpen(true)}
        className="mx-auto mt-10 flex min-h-11 items-center justify-center gap-2 rounded-full px-4 text-xs text-muted transition-colors hover:text-foreground"
      >
        <Keyboard className="size-3.5" aria-hidden /> Pressione ? para ver os atalhos do painel
      </button>
    </MerchantProvider>
  );
}

function Shell() {
  usePageTitle("Painel do lojista");
  const user = useAuth((s) => s.user);
  const ownsStore = useOwnsStore();
  const scope = merchantScope(user);
  const search = route.useSearch();
  const tab = parseTab(search.aba);
  const days = parsePeriod(search.dias);
  const merchantId = scope.ids.includes(search.loja ?? "")
    ? (search.loja as string)
    : scope.initial;
  const merchant = SEED_MERCHANTS.find((m) => m.id === merchantId);

  const ctx: MerchantCtx = {
    merchantId,
    merchantName: merchant?.name ?? "Loja",
    days,
    tab,
    ownsStore,
    isAdmin: Boolean(user?.roles.includes("admin")),
    fresh: new Set(),
    openOrderId: search.pedido,
    creatingProduct: search.novo === true,
  };

  return (
    <div className="relative isolate overflow-hidden">
      <div className="aurora opacity-60" aria-hidden>
        <i />
        <i />
        <i />
      </div>
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-12 min-[1800px]:max-w-[100rem]">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-title">
              Painel do <span className="serif text-primary">lojista</span>
            </h1>
            <p className="mt-2 text-muted">
              Vendas, pedidos, estoque e catálogo de {merchant?.name ?? "sua loja"}, em tempo real.
            </p>
          </div>
          {scope.canReconcile && <ReconciliationSeal />}
        </div>
        <MerchantProvider value={ctx}>
          <Panel scopeIds={scope.ids} />
        </MerchantProvider>
      </div>
    </div>
  );
}

export default function MerchantPage() {
  const user = useAuth((s) => s.user);
  if (!merchantScope(user).allowed) return <Forbidden />;
  return <Shell />;
}
