import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { MerchantOrder } from "@/api/merchant";

import { formatMoney, shortId } from "@/lib/format";
import { detectOrderChanges, snapshotStatuses } from "@/lib/merchant-metrics";
import { toast } from "@/lib/toast";

const FRESH_MS = 6_000;

export function useLiveOrders(orders: MerchantOrder[] | undefined, onOpen: (id: string) => void) {
  const client = useQueryClient();
  const known = useRef<Map<string, string> | null>(null);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());
  const open = useRef(onOpen);
  open.current = onOpen;
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    if (!orders) return;
    const changes = detectOrderChanges(known.current, orders);
    known.current = snapshotStatuses(orders);
    const touched = [...changes.paid, ...changes.created];
    if (touched.length === 0) return;

    if (changes.paid.length > 0) {
      const sale = changes.paid[0] as MerchantOrder;
      const total = changes.paid.reduce((n, o) => n + o.subtotal_cents, 0);
      void toast.success(
        changes.paid.length === 1
          ? `Nova venda de ${formatMoney(sale.subtotal_cents)}`
          : `${changes.paid.length} novas vendas, ${formatMoney(total)}`,
        {
          description:
            changes.paid.length === 1
              ? `${sale.customer_name}, pedido ${shortId(sale.id)}`
              : "O painel já foi atualizado.",
          action: { label: "Ver pedido", onClick: () => open.current(sale.id) },
        },
      );
    } else {
      const order = changes.created[0] as MerchantOrder;
      void toast.message(
        changes.created.length === 1
          ? "Novo pedido aguardando o PIX"
          : `${changes.created.length} novos pedidos aguardando o PIX`,
        {
          description: `${order.customer_name}, ${formatMoney(order.subtotal_cents)}`,
          action: { label: "Ver pedido", onClick: () => open.current(order.id) },
        },
      );
    }

    setFresh(new Set(touched.map((o) => o.id)));
    for (const key of [
      ["summary"],
      ["entries"],
      ["merchant-stock"],
      ["merchant-ledger"],
      ["reconciliation"],
    ]) {
      void client.invalidateQueries({ queryKey: key });
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setFresh(new Set()), FRESH_MS);
  }, [orders, client]);

  return fresh;
}
