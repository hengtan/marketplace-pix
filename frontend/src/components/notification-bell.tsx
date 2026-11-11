import { useQuery } from "@tanstack/react-query";
import { Bell, Mail } from "lucide-react";
import { Popover } from "radix-ui";
import { useState } from "react";
import { fetchText } from "@/api/client";
import type { Notification } from "@/api/schemas";
import { useNotifications } from "@/hooks/queries";
import { formatDateTime } from "@/lib/format";
import { useCustomerId } from "@/store/customer";
import { Dialog, DialogContent } from "./ui/dialog";
import { Badge } from "./ui/misc";

const KIND_LABEL: Record<Notification["kind"], string> = {
  ORDER_CREATED: "Pedido recebido",
  PIX_READY: "PIX pronto",
  ORDER_PAID: "Pagamento confirmado",
  ORDER_CANCELLED: "Pedido cancelado",
};

const STATUS_LABEL: Record<Notification["status"], string> = {
  QUEUED: "Na fila",
  SENT: "Enviado",
  FAILED: "Falhou",
};

function EmailPreview({
  notification,
  onClose,
}: {
  notification: Notification | null;
  onClose: () => void;
}) {
  const id = notification?.id;
  const { data, isLoading, isError } = useQuery({
    queryKey: ["notification-html", id],
    queryFn: () => fetchText(`/api/notifications/${id}/preview`),
    enabled: Boolean(id),
    staleTime: Number.POSITIVE_INFINITY,
  });
  return (
    <Dialog open={Boolean(notification)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        title={notification?.subject ?? "E-mail"}
        description="Pré-visualização do e-mail enviado"
        className="h-[80dvh] max-w-2xl p-6"
      >
        <div className="mt-4 flex-1 overflow-hidden rounded-md border border-border bg-white">
          {isLoading && <div className="skeleton size-full" />}
          {isError && (
            <p className="p-6 text-sm text-danger">Não foi possível carregar o e-mail.</p>
          )}
          {data && (
            <iframe title="Conteúdo do e-mail" sandbox="" srcDoc={data} className="size-full" />
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function NotificationBell() {
  const customerId = useCustomerId();
  const { data } = useNotifications(customerId);
  const [selected, setSelected] = useState<Notification | null>(null);
  const [open, setOpen] = useState(false);
  const items = data?.items ?? [];

  return (
    <>
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <button
            type="button"
            aria-label={`Notificações${items.length ? `, ${items.length} e-mails` : ""}`}
            className="relative grid size-11 place-items-center rounded-full transition-colors hover:bg-surface-2"
          >
            <Bell className="size-5" />
            {items.length > 0 && (
              <span className="absolute top-2 right-2 size-2.5 rounded-full bg-pix ring-2 ring-background" />
            )}
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            align="end"
            sideOffset={8}
            className="z-50 w-[min(24rem,calc(100vw-2rem))] rounded-lg border border-border bg-surface p-2 shadow-lift data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95"
          >
            <h2 className="px-3 pt-2 pb-1 font-sans text-sm font-semibold tracking-normal">
              E-mails do seu pedido
            </h2>
            {items.length === 0 ? (
              <p className="px-3 py-8 text-center text-sm text-muted">
                Quando você fizer um pedido, os e-mails aparecem aqui.
              </p>
            ) : (
              <ul className="max-h-80 overflow-y-auto">
                {items.map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setOpen(false);
                        setSelected(n);
                      }}
                      className="flex w-full items-start gap-3 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-surface-2"
                    >
                      <Mail className="mt-0.5 size-4 shrink-0 text-primary" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium">{n.subject}</span>
                        <span className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                          {KIND_LABEL[n.kind]}, {formatDateTime(n.created_at)}
                        </span>
                      </span>
                      <Badge
                        tone={
                          n.status === "FAILED" ? "danger" : n.status === "SENT" ? "pix" : "neutral"
                        }
                      >
                        {STATUS_LABEL[n.status]}
                      </Badge>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
      <EmailPreview notification={selected} onClose={() => setSelected(null)} />
    </>
  );
}
