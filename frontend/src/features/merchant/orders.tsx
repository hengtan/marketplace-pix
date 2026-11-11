import { RefreshCw, Search } from "lucide-react";
import { m } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import type { MerchantOrder } from "@/api/merchant";

import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { useMerchantOrders } from "@/hooks/merchant";
import { formatDateTime, formatMoney, shortId } from "@/lib/format";
import { formatRelative, formatTime } from "@/lib/format-merchant";
import {
  countByStatus,
  filterOrders,
  orderStatus,
  orderUnits,
  paginate,
  type StatusFilter,
} from "@/lib/merchant-metrics";
import { EASE } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useMerchant, useMerchantNav } from "./context";
import { useStockRows } from "./data";
import { OrderDrawer } from "./order-drawer";
import { Card, Pager, Segmented, StatusBadge, TableSkeleton } from "./ui";

const PAGE_SIZE = 10;

const FILTERS: StatusFilter[] = ["ALL", "PAID", "PENDING", "CANCELLED"];
const FILTER_LABEL: Record<StatusFilter, string> = {
  ALL: "Todos",
  PAID: "Pagos",
  PENDING: "Aguardando",
  CANCELLED: "Cancelados",
};

function itemsSummary(order: MerchantOrder, names: Map<string, string>): string {
  const first = order.items[0];
  if (!first) return "-";
  const label = `${first.quantity}× ${names.get(first.product_id) ?? `Produto ${shortId(first.product_id)}`}`;
  return order.items.length > 1 ? `${label} +${order.items.length - 1}` : label;
}

export function Orders() {
  const { ownsStore, days, fresh } = useMerchant();
  const nav = useMerchantNav();
  const query = useMerchantOrders(ownsStore);
  const { productMap } = useStockRows();
  const [status, setStatus] = useState<StatusFilter>("ALL");
  const [text, setText] = useState("");
  const [page, setPage] = useState(1);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const names = useMemo(
    () => new Map([...productMap].map(([id, p]) => [id, p.name])),
    [productMap],
  );
  const all = query.data?.items;
  const since = now - days * 86_400_000;
  const inPeriod = useMemo(
    () => filterOrders(all ?? [], { status: "ALL", query: "", sinceMs: since }),
    [all, since],
  );
  const counts = useMemo(() => countByStatus(inPeriod), [inPeriod]);
  const filtered = useMemo(
    () =>
      filterOrders(inPeriod, {
        status,
        query: text,
        names: Object.fromEntries(names),
      }),
    [inPeriod, status, text, names],
  );
  const view = paginate(filtered, page, PAGE_SIZE);
  const total = filtered.reduce(
    (n, o) => n + (orderStatus(o.status) === "CANCELLED" ? 0 : o.subtotal_cents),
    0,
  );

  if (!ownsStore) {
    return (
      <EmptyState
        art="orders"
        title="Contas de administrador não têm pedidos de loja"
        description="Esta aba mostra os pedidos da loja da conta conectada. Entre com uma conta de lojista para acompanhar vendas em tempo real."
      />
    );
  }

  return (
    <Card aria-labelledby="pedidos-titulo">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="pedidos-titulo" className="font-display text-xl font-semibold">
            Pedidos
          </h2>
          <p className="mt-1 flex items-center gap-2 text-sm text-muted">
            <span className="relative grid size-2 place-items-center">
              <span className="live-dot absolute inset-0 rounded-full" aria-hidden />
              <span className="size-2 rounded-full bg-pix" />
            </span>
            <span>
              Atualiza sozinho a cada 10 segundos
              {query.dataUpdatedAt > 0 && (
                <span className="tabular">, última às {formatTime(query.dataUpdatedAt)}</span>
              )}
            </span>
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => query.refetch()}
          disabled={query.isFetching}
        >
          <RefreshCw className={cn(query.isFetching && "animate-spin")} aria-hidden /> Atualizar
        </Button>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1 basis-64">
          <Search
            className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted"
            aria-hidden
          />
          <Input
            type="search"
            data-merchant-search
            aria-label="Buscar pedidos por cliente, produto ou código"
            placeholder="Buscar por cliente, produto ou código"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setPage(1);
            }}
            className="h-11 pl-10"
          />
        </div>
        <Segmented
          id="orders-status-pill"
          label="Filtrar por status"
          options={FILTERS}
          value={status}
          onChange={(v) => {
            setStatus(v);
            setPage(1);
          }}
          render={(f) => (
            <>
              {FILTER_LABEL[f]} <span className="tabular opacity-70">{counts[f]}</span>
            </>
          )}
        />
      </div>

      <div className="mt-5">
        {query.isError ? (
          <ErrorState
            error={query.error}
            onRetry={() => query.refetch()}
            title="Não foi possível carregar os pedidos"
          />
        ) : query.isPending ? (
          <TableSkeleton rows={8} />
        ) : filtered.length === 0 ? (
          <EmptyState
            art="orders"
            title={
              inPeriod.length === 0 ? "Nenhum pedido neste período" : "Nenhum pedido encontrado"
            }
            description={
              inPeriod.length === 0
                ? "Quando alguém comprar da sua loja, o pedido aparece aqui na hora."
                : "Tente outro status ou limpe a busca."
            }
            action={
              inPeriod.length > 0 ? (
                <Button
                  variant="outline"
                  onClick={() => {
                    setStatus("ALL");
                    setText("");
                  }}
                >
                  Limpar filtros
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Pedidos com itens da sua loja</caption>
              <thead className="text-xs tracking-wide text-muted uppercase">
                <tr className="border-b border-border">
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Pedido
                  </th>
                  <th scope="col" className="hidden py-2 pr-4 font-medium md:table-cell">
                    Cliente
                  </th>
                  <th scope="col" className="hidden py-2 pr-4 font-medium lg:table-cell">
                    Itens
                  </th>
                  <th scope="col" className="hidden py-2 pr-4 font-medium sm:table-cell">
                    Quando
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Status
                  </th>
                  <th scope="col" className="py-2 text-right font-medium">
                    Valor
                  </th>
                </tr>
              </thead>
              <tbody>
                {view.items.map((o, i) => (
                  <m.tr
                    key={o.id}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.4, delay: Math.min(i, 10) * 0.035, ease: EASE }}
                    onClick={() => nav.openOrder(o.id)}
                    data-testid="merchant-order-row"
                    className={cn(
                      "cursor-pointer border-b border-border/60 transition-colors last:border-0 hover:bg-primary-soft/40",
                      fresh.has(o.id) && "row-flash",
                    )}
                  >
                    <td className="py-3 pr-4">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          nav.openOrder(o.id);
                        }}
                        aria-label={`Abrir pedido ${shortId(o.id)}`}
                        className="rounded-md font-mono text-[0.8rem] font-medium text-primary hover:underline"
                      >
                        {shortId(o.id)}
                      </button>
                      <span className="block max-w-[12rem] truncate text-xs text-muted md:hidden">
                        {o.customer_name}
                      </span>
                    </td>
                    <td className="hidden py-3 pr-4 md:table-cell">{o.customer_name}</td>
                    <td className="hidden max-w-[16rem] truncate py-3 pr-4 text-muted lg:table-cell">
                      {itemsSummary(o, names)}
                      <span className="sr-only">, {orderUnits(o)} unidades</span>
                    </td>
                    <td
                      className="tabular hidden py-3 pr-4 whitespace-nowrap text-muted sm:table-cell"
                      title={formatDateTime(o.created_at)}
                    >
                      {formatRelative(o.created_at, now)}
                    </td>
                    <td className="py-3 pr-4">
                      <StatusBadge status={o.status} />
                    </td>
                    <td className="tabular py-3 text-right font-semibold whitespace-nowrap">
                      {formatMoney(o.subtotal_cents)}
                    </td>
                  </m.tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {!query.isPending && filtered.length > 0 && (
        <Pager
          page={view.page}
          pages={view.pages}
          onChange={setPage}
          label="Paginação dos pedidos"
          info={`${filtered.length} ${filtered.length === 1 ? "pedido" : "pedidos"}, ${formatMoney(total)} sem contar cancelados${
            query.data && query.data.total > query.data.items.length
              ? `. Mostrando os ${query.data.items.length} mais recentes de ${query.data.total}`
              : ""
          }`}
        />
      )}
      <OrderDrawer orders={all} names={names} />
    </Card>
  );
}
