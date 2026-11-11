import { useEffect, useRef } from "react";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/misc";
import { MERCHANT_TABS } from "@/lib/merchant-metrics";
import { useMerchantNav } from "./context";

const SEQUENCE_MS = 1200;

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.closest("[role=combobox], [role=listbox]") !== null
  );
}

export function useMerchantShortcuts(onHelp: () => void) {
  const nav = useMerchantNav();
  const pending = useRef(0);
  const help = useRef(onHelp);
  help.current = onHelp;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
      if (isEditable(e.target)) return;
      if (document.querySelector("[role=dialog]")) return;

      const key = e.key.toLowerCase();
      if (pending.current && Date.now() - pending.current < SEQUENCE_MS) {
        pending.current = 0;
        const tab = MERCHANT_TABS.find((t) => t.key === key);
        if (tab) {
          e.preventDefault();
          void nav.go(tab.id);
          return;
        }
      }
      pending.current = 0;
      if (key === "g") {
        pending.current = Date.now();
      } else if (e.key === "?") {
        e.preventDefault();
        help.current();
      } else if (key === "n") {
        e.preventDefault();
        void nav.newProduct();
      } else if (key === "/") {
        const field = document.querySelector<HTMLInputElement>("[data-merchant-search]");
        if (field) {
          e.preventDefault();
          field.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [nav]);
}

const OTHER = [
  { keys: ["n"], label: "Novo produto" },
  { keys: ["/"], label: "Buscar na aba atual" },
  { keys: ["?"], label: "Mostrar esta ajuda" },
  { keys: ["⌘", "K"], label: "Paleta de comandos (Ctrl K no Windows)" },
  { keys: ["Esc"], label: "Fechar painel lateral ou janela" },
];

function Row({ keys, label }: { keys: string[]; label: string }) {
  return (
    <li className="flex items-center justify-between gap-4 py-2.5">
      <span>{label}</span>
      <span className="flex items-center gap-1.5">
        {keys.map((k, i) => (
          <span key={`${k}-${i}`} className="flex items-center gap-1.5">
            {i > 0 && keys[0] === "g" && <span className="text-xs text-muted">depois</span>}
            <Kbd>{k}</Kbd>
          </span>
        ))}
      </span>
    </li>
  );
}

export function ShortcutsHelp({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="Atalhos de teclado"
        description="Funcionam em qualquer aba do painel, fora dos campos de texto."
        className="max-h-[90dvh] max-w-md overflow-y-auto p-6"
      >
        <h3 className="mt-5 text-sm font-medium text-muted">Ir para</h3>
        <ul className="divide-y divide-border">
          {MERCHANT_TABS.map((t) => (
            <Row key={t.id} keys={["g", t.key.toUpperCase()]} label={t.label} />
          ))}
        </ul>
        <h3 className="mt-5 text-sm font-medium text-muted">Ações</h3>
        <ul className="divide-y divide-border">
          {OTHER.map((o) => (
            <Row key={o.label} keys={o.keys} label={o.label} />
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
