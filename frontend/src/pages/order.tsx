import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getRouteApi, Link, useNavigate } from "@tanstack/react-router";
import { Ban, ClipboardList, Hourglass, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { api } from "@/api/endpoints";
import type { Order } from "@/api/schemas";
import { ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Badge, Skeleton } from "@/components/ui/misc";
import { OrderTimeline } from "@/features/order-timeline";
import { PixPanel } from "@/features/pix-panel";
import { SuccessMark } from "@/features/success-mark";
import { qk } from "@/hooks/queries";
import { useOrderStatus } from "@/hooks/useOrderStatus";
import { usePageTitle } from "@/hooks/utils";
import { env } from "@/lib/env";
import { formatMoney, shortId } from "@/lib/format";
import { friendlyCancelReason } from "@/lib/merchants";
import { useCart } from "@/store/cart";

const route = getRouteApi("/pedido/$id");

export function OrderStatusBadge({ status }: { status: Order["status"] }) {
  if (status === "PAID") return <Badge tone="pix">Pago</Badge>;
  if (status === "CANCELLED") return <Badge tone="danger">Cancelado</Badge>;
  return <Badge tone="warn">Aguardando PIX</Badge>;
}

function OrderItems({ order }: { order: Order }) {
  const ids = order.items.map((i) => i.product_id);
  const { data } = useQuery({
    queryKey: ["products-by-ids", ids.join(",")],
    queryFn: () => api.productsByIds(ids),
    staleTime: 5 * 60_000,
  });
  return (
    <div>
      <h2 className="font-display text-xl font-semibold">Itens do pedido</h2>
      <ul className="mt-3 divide-y divide-border">
        {order.items.map((i) => {
          const p = data?.find((x) => x.id === i.product_id);
          return (
            <li key={i.product_id} className="flex items-start justify-between gap-4 py-3">
              <div className="min-w-0">
                {p ? (
                  <Link
                    to="/produto/$slug"
                    params={{ slug: p.slug }}
                    className="font-medium hover:text-primary"
                  >
                    {p.name}
                  </Link>
                ) : (
                  <Skeleton className="h-5 w-40" />
                )}
                <p className="tabular text-sm text-muted">
                  {i.quantity} x {formatMoney(i.unit_price_cents)}
                </p>
              </div>
              <span className="tabular font-semibold">
                {formatMoney(i.quantity * i.unit_price_cents)}
              </span>
            </li>
          );
        })}
      </ul>
      <div className="flex items-baseline justify-between border-t border-border pt-4">
        <span className="font-medium">Total</span>
        <span className="tabular font-display text-2xl font-bold">
          {formatMoney(order.total_cents)}
        </span>
      </div>
    </div>
  );
}

function Redo({ order }: { order: Order }) {
  const navigate = useNavigate();
  const add = useCart((s) => s.add);
  const redo = useMutation({
    mutationFn: () => api.productsByIds(order.items.map((i) => i.product_id)),
    onSuccess: (products) => {
      for (const item of order.items) {
        const p = products.find((x) => x.id === item.product_id);
        if (p) add(p, item.quantity);
      }
      navigate({ to: "/checkout" });
    },
    onError: (e) => toast.error(e.message),
  });
  return (
    <Button size="lg" onClick={() => redo.mutate()} disabled={redo.isPending}>
      <RefreshCw /> {redo.isPending ? "Preparando..." : "Refazer pedido"}
    </Button>
  );
}

export default function OrderPage() {
  const { id } = route.useParams();
  const client = useQueryClient();
  const { order, payment, isLoading, error } = useOrderStatus(id);
  usePageTitle(order ? `Pedido ${shortId(order.id)}` : "Pedido");

  const simulate = useMutation({
    mutationFn: () => {
      if (!payment) throw new Error("PIX ainda não gerado");
      return api.devPay(payment.psp_charge_id);
    },
    onSuccess: () => {
      client.invalidateQueries({ queryKey: qk.order(id) });
      client.invalidateQueries({ queryKey: qk.payment(id) });
    },
    onError: (e) => toast.error(e.message),
  });

  if (isLoading) {
    return (
      <div className="mx-auto grid max-w-5xl gap-6 px-4 py-10 sm:px-6" aria-busy>
        <Skeleton className="h-12 w-1/2" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  if (error || !order) {
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <ErrorState
          title={missing ? "Pedido não encontrado" : "Não foi possível carregar o pedido"}
          message={missing ? "Confira o link ou veja seus pedidos recentes." : error?.message}
          onRetry={missing ? undefined : () => client.invalidateQueries({ queryKey: qk.order(id) })}
        />
        <div className="flex justify-center">
          <Button asChild variant="outline">
            <Link to="/pedidos">Meus pedidos</Link>
          </Button>
        </div>
      </div>
    );
  }

  const paid = order.status === "PAID";
  const cancelled = order.status === "CANCELLED";

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-12">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-4xl font-bold sm:text-5xl">Pedido {shortId(order.id)}</h1>
        <OrderStatusBadge status={order.status} />
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-[1.4fr_1fr]">
        <div className="grid content-start gap-6">
          {paid && (
            <section
              aria-live="polite"
              className="rounded-xl border border-pix/50 bg-pix-soft p-8 text-center"
              data-testid="order-paid"
            >
              <SuccessMark />
              <h2 className="mt-4 text-3xl font-bold text-pix-ink">Pagamento confirmado</h2>
              <p className="mx-auto mt-2 max-w-[40ch] text-pix-ink/80">
                Recebemos {formatMoney(order.total_cents)}. Enviamos a confirmação para{" "}
                {order.customer_email}.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-3">
                <Button asChild>
                  <Link to="/">Continuar comprando</Link>
                </Button>
                <Button asChild variant="outline">
                  <Link to="/pedidos">
                    <ClipboardList /> Meus pedidos
                  </Link>
                </Button>
              </div>
            </section>
          )}

          {cancelled && (
            <section
              role="alert"
              className="rounded-xl border border-danger/40 bg-danger-soft p-8"
              data-testid="order-cancelled"
            >
              <div className="flex items-start gap-4">
                <span className="grid size-12 shrink-0 place-items-center rounded-full bg-danger text-primary-foreground">
                  {order.cancel_reason === "payment expired" ? (
                    <Hourglass className="size-6" />
                  ) : (
                    <Ban className="size-6" />
                  )}
                </span>
                <div>
                  <h2 className="text-2xl font-bold">
                    {order.cancel_reason === "payment expired"
                      ? "O PIX expirou"
                      : "Pedido cancelado"}
                  </h2>
                  <p className="mt-1 max-w-[46ch]">{friendlyCancelReason(order.cancel_reason)}</p>
                  <div className="mt-5">
                    <Redo order={order} />
                  </div>
                </div>
              </div>
            </section>
          )}

          {!paid &&
            !cancelled &&
            (payment ? (
              <PixPanel
                pixCode={payment.pix_code}
                amountCents={payment.amount_cents}
                expiresAt={payment.expires_at}
                onSimulate={env.devTools ? () => simulate.mutate() : undefined}
                simulating={simulate.isPending}
              />
            ) : (
              <section
                className="grid place-items-center gap-3 rounded-xl border border-border bg-surface p-12 text-center"
                aria-busy
              >
                <span className="size-10 animate-spin rounded-full border-4 border-primary-soft border-t-primary" />
                <p className="font-display text-xl font-semibold">Gerando o seu PIX</p>
                <p className="text-muted">Estamos reservando o estoque. Leva poucos segundos.</p>
              </section>
            ))}

          <section className="rounded-xl border border-border bg-surface p-6">
            <OrderItems order={order} />
          </section>
        </div>

        <aside
          className="h-fit rounded-xl border border-border bg-surface p-6 lg:sticky lg:top-24"
          aria-labelledby="timeline-title"
        >
          <h2 id="timeline-title" className="mb-5 font-display text-xl font-semibold">
            Andamento
          </h2>
          <OrderTimeline order={order} payment={payment} />
        </aside>
      </div>
    </div>
  );
}
