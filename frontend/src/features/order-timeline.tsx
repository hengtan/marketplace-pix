import { Check, CircleDashed, X } from "lucide-react";
import type { Order, Payment } from "@/api/schemas";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Step {
  id: string;
  label: string;
  detail?: string;
  state: "done" | "current" | "pending" | "failed";
}

export function buildSteps(order: Order, payment: Payment | undefined): Step[] {
  const steps: Step[] = [
    { id: "created", label: "Pedido criado", detail: formatDateTime(order.created_at), state: "done" },
    {
      id: "pix",
      label: "PIX gerado",
      detail: payment ? "Estoque reservado" : "Reservando o estoque",
      state: payment ? "done" : order.status === "CANCELLED" ? "failed" : "current",
    },
  ];
  if (order.status === "PAID") {
    steps.push({
      id: "paid",
      label: "Pagamento confirmado",
      detail: payment?.confirmed_at ? formatDateTime(payment.confirmed_at) : undefined,
      state: "done",
    });
  } else if (order.status === "CANCELLED") {
    steps.push({ id: "cancelled", label: "Pedido cancelado", state: "failed" });
  } else {
    steps.push({
      id: "paid",
      label: "Aguardando pagamento",
      detail: payment ? "Atualizamos sozinhos" : undefined,
      state: payment ? "current" : "pending",
    });
  }
  return steps;
}

export function OrderTimeline({ order, payment }: { order: Order; payment: Payment | undefined }) {
  const steps = buildSteps(order, payment);
  return (
    <ol aria-label="Linha do tempo do pedido" className="grid gap-0">
      {steps.map((s, i) => (
        <li key={s.id} className="relative grid grid-cols-[2rem_1fr] gap-4 pb-6 last:pb-0" aria-current={s.state === "current" ? "step" : undefined}>
          {i < steps.length - 1 && (
            <span
              aria-hidden
              className={cn("absolute top-8 bottom-0 left-4 w-px -translate-x-1/2", s.state === "done" ? "bg-pix" : "bg-border")}
            />
          )}
          <span
            className={cn(
              "relative grid size-8 place-items-center rounded-full",
              s.state === "done" && "bg-pix text-[oklch(0.2_0.06_165)]",
              s.state === "current" && "bg-primary-soft text-primary",
              s.state === "pending" && "bg-surface-2 text-muted",
              s.state === "failed" && "bg-danger-soft text-danger",
            )}
          >
            {s.state === "done" && <Check className="size-4" strokeWidth={3} />}
            {s.state === "current" && (
              <>
                <span className="absolute inset-0 animate-[pulse-ring_2s_ease-out_infinite] rounded-full bg-primary/40" />
                <CircleDashed className="relative size-4" />
              </>
            )}
            {s.state === "pending" && <CircleDashed className="size-4" />}
            {s.state === "failed" && <X className="size-4" strokeWidth={3} />}
          </span>
          <div className="pt-1">
            <p className="font-medium">{s.label}</p>
            {s.detail && <p className="text-sm text-muted">{s.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}
