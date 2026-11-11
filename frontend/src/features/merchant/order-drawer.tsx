import { Check, Copy, Hourglass, PackageCheck, X } from "lucide-react";
import { m } from "motion/react";
import type { MerchantOrder } from "@/api/merchant";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useCopy } from "@/hooks/utils";
import { formatDateTime, formatMoney, shortId } from "@/lib/format";
import { ORDER_STATUS_LABEL, orderStatus } from "@/lib/merchant-metrics";
import { EASE } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useMerchant, useMerchantNav } from "./context";
import { StatusBadge } from "./ui";

const FEE_RATE = 0.1;

function Timeline({ order }: { order: MerchantOrder }) {
  const status = orderStatus(order.status);
  const steps = [
    {
      icon: Check,
      title: "Pedido recebido",
      detail: formatDateTime(order.created_at),
      state: "done" as const,
    },
    {
      icon: status === "CANCELLED" ? X : status === "PAID" ? Check : Hourglass,
      title:
        status === "PAID"
          ? "PIX confirmado"
          : status === "CANCELLED"
            ? "Pedido cancelado"
            : "Aguardando o PIX",
      detail:
        status === "PAID"
          ? "O pagamento caiu e o estoque foi baixado."
          : status === "CANCELLED"
            ? "Nenhum valor foi cobrado e o estoque reservado voltou."
            : "O cliente tem alguns minutos para pagar.",
      state:
        status === "PENDING"
          ? ("active" as const)
          : status === "CANCELLED"
            ? ("failed" as const)
            : ("done" as const),
    },
    {
      icon: PackageCheck,
      title: "Valor no seu extrato",
      detail:
        status === "PAID"
          ? "Crédito líquido lançado no livro-razão."
          : "Só acontece depois do pagamento.",
      state: status === "PAID" ? ("done" as const) : ("idle" as const),
    },
  ];
  return (
    <ol className="grid gap-0" aria-label="Linha do tempo do pedido">
      {steps.map((s, i) => (
        <m.li
          key={s.title}
          initial={{ opacity: 0, x: 10 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.45, delay: 0.1 + i * 0.09, ease: EASE }}
          className="relative flex gap-3 pb-5 last:pb-0"
        >
          {i < steps.length - 1 && (
            <span aria-hidden className="absolute top-8 bottom-0 left-4 w-px bg-border" />
          )}
          <span
            className={cn(
              "relative z-10 grid size-8 shrink-0 place-items-center rounded-full",
              s.state === "done" && "bg-pix text-[oklch(0.2_0.06_165)]",
              s.state === "active" && "bg-warn-soft text-warn ring-2 ring-warn/40",
              s.state === "failed" && "bg-danger-soft text-danger",
              s.state === "idle" && "bg-surface-2 text-muted",
            )}
          >
            <s.icon className="size-4" aria-hidden />
          </span>
          <span className="grid gap-0.5">
            <span className="font-medium">{s.title}</span>
            <span className="text-sm text-muted">{s.detail}</span>
          </span>
        </m.li>
      ))}
    </ol>
  );
}

export function OrderDrawer({
  orders,
  names,
}: {
  orders: MerchantOrder[] | undefined;
  names: Map<string, string>;
}) {
  const { openOrderId } = useMerchant();
  const nav = useMerchantNav();
  const { copied, copy } = useCopy();
  const order = orders?.find((o) => o.id === openOrderId);
  const fee = order ? Math.round(order.subtotal_cents * FEE_RATE) : 0;
  const status = order ? orderStatus(order.status) : null;

  return (
    <Dialog open={Boolean(openOrderId)} onOpenChange={(open) => !open && nav.closeOrder()}>
      <DialogContent
        side="right"
        title={order ? `Pedido ${shortId(order.id)}` : "Pedido"}
        description="Detalhes dos itens da sua loja neste pedido"
        className="max-w-lg overflow-y-auto p-6 pr-16"
      >
        {!order ? (
          <p className="mt-6 text-muted">
            Este pedido não está entre os mais recentes carregados. Atualize a lista ou busque pelo
            código.
          </p>
        ) : (
          <div className="mt-5 grid gap-6">
            <div className="flex flex-wrap items-center gap-3">
              <StatusBadge status={order.status} />
              <span className="text-sm text-muted">{formatDateTime(order.created_at)}</span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => copy(order.id)}
                aria-label="Copiar código completo do pedido"
              >
                {copied ? <Check aria-hidden /> : <Copy aria-hidden />}{" "}
                {copied ? "Copiado" : "Copiar código"}
              </Button>
              <span className="sr-only" role="status">
                {copied ? "Código copiado" : ""}
              </span>
            </div>

            <section aria-labelledby="drawer-cliente">
              <h3 id="drawer-cliente" className="text-sm font-medium text-muted">
                Cliente
              </h3>
              <p className="mt-1 text-lg font-semibold">{order.customer_name}</p>
              <p className="text-sm text-muted">
                Por privacidade, o e-mail do cliente não é exibido ao lojista.
              </p>
            </section>

            <section aria-labelledby="drawer-itens">
              <h3 id="drawer-itens" className="text-sm font-medium text-muted">
                Itens da sua loja
              </h3>
              <table className="mt-2 w-full text-left text-sm">
                <caption className="sr-only">Itens do pedido</caption>
                <thead className="sr-only">
                  <tr>
                    <th scope="col">Produto</th>
                    <th scope="col">Quantidade</th>
                    <th scope="col">Subtotal</th>
                  </tr>
                </thead>
                <tbody>
                  {order.items.map((i) => (
                    <tr key={i.product_id} className="border-b border-border/60 last:border-0">
                      <td className="py-2.5 pr-3">
                        {names.get(i.product_id) ?? `Produto ${shortId(i.product_id)}`}
                        <span className="tabular block text-xs text-muted">
                          {formatMoney(i.unit_price_cents)} cada
                        </span>
                      </td>
                      <td className="tabular py-2.5 pr-3 text-muted">{i.quantity}×</td>
                      <td className="tabular py-2.5 text-right font-medium">
                        {formatMoney(i.quantity * i.unit_price_cents)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <dl className="tabular mt-3 grid gap-1.5 rounded-2xl bg-surface-2 p-4 text-sm">
                <div className="flex justify-between">
                  <dt className="text-muted">Subtotal</dt>
                  <dd>{formatMoney(order.subtotal_cents)}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted">Taxa da plataforma (10%)</dt>
                  <dd>-{formatMoney(fee)}</dd>
                </div>
                <div className="flex justify-between border-t border-border pt-2 font-semibold">
                  <dt>{status === "PAID" ? "Você recebe" : "Você receberia"}</dt>
                  <dd className={status === "PAID" ? "text-pix-ink" : undefined}>
                    {formatMoney(order.subtotal_cents - fee)}
                  </dd>
                </div>
              </dl>
            </section>

            <section aria-labelledby="drawer-tempo">
              <h3 id="drawer-tempo" className="mb-3 text-sm font-medium text-muted">
                Andamento
              </h3>
              <Timeline order={order} />
              <p className="sr-only">Situação atual: {status ? ORDER_STATUS_LABEL[status] : ""}</p>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
