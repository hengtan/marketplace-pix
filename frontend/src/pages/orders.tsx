import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/misc";
import { useOrders } from "@/hooks/queries";
import { usePageTitle } from "@/hooks/utils";
import { formatDateTime, formatMoney, pluralize, shortId } from "@/lib/format";
import { getCustomerId } from "@/store/customer";
import { OrderStatusBadge } from "./order";

export default function OrdersPage() {
  usePageTitle("Meus pedidos");
  const [page, setPage] = useState(1);
  const { data, isPending, isError, error, refetch } = useOrders(getCustomerId(), page);
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 sm:py-12">
      <h1 className="text-4xl font-bold sm:text-5xl">Meus pedidos</h1>
      <p className="mt-2 text-muted">Acompanhe pagamentos e abra o PIX de pedidos pendentes.</p>

      <div className="mt-8">
        {isPending ? (
          <ul className="grid gap-3" aria-busy>
            {[0, 1, 2].map((i) => (
              <li key={i}>
                <Skeleton className="h-24 w-full rounded-lg" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <ErrorState message={error.message} onRetry={() => refetch()} />
        ) : data.items.length === 0 ? (
          <EmptyState
            art="orders"
            title="Você ainda não fez pedidos"
            description="Quando você pagar um PIX, o pedido aparece aqui."
            action={
              <Button asChild>
                <Link to="/">Ver produtos</Link>
              </Button>
            }
          />
        ) : (
          <>
            <ul className="grid gap-3">
              {data.items.map((o) => {
                const qty = o.items.reduce((n, i) => n + i.quantity, 0);
                return (
                  <li key={o.id}>
                    <Link
                      to="/pedido/$id"
                      params={{ id: o.id }}
                      className="grid gap-2 rounded-lg border border-border bg-surface p-5 transition-[border-color,box-shadow] hover:border-primary hover:shadow-soft sm:grid-cols-[1fr_auto] sm:items-center"
                      data-testid="order-row"
                    >
                      <span>
                        <span className="flex flex-wrap items-center gap-3">
                          <span className="font-display text-xl font-semibold">
                            Pedido {shortId(o.id)}
                          </span>
                          <OrderStatusBadge status={o.status} />
                        </span>
                        <span className="mt-1 block text-sm text-muted">
                          {formatDateTime(o.created_at)}, {qty} {pluralize(qty, "item", "itens")}
                        </span>
                      </span>
                      <span className="tabular font-display text-2xl font-bold">
                        {formatMoney(o.total_cents)}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
            {pages > 1 && (
              <nav aria-label="Paginação" className="mt-6 flex items-center justify-center gap-4">
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
                  Página {page} de {pages}
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
          </>
        )}
      </div>
    </div>
  );
}
