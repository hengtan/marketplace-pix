import { useNavigate } from "@tanstack/react-router";
import { Command } from "cmdk";
import {
  ClipboardList,
  CornerDownLeft,
  Moon,
  Search,
  ShoppingBag,
  Sparkles,
  Store,
  Sun,
  Tag,
} from "lucide-react";
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { useAssistantChat } from "@/features/assistant/store";
import { useOrders, useProductSearch } from "@/hooks/queries";
import { useDebounced } from "@/hooks/utils";
import { formatMoney, shortId } from "@/lib/format";
import { useCustomerId } from "@/store/customer";
import { useTheme } from "@/store/theme";
import { useUi } from "@/store/ui";
import { Dialog, DialogContent } from "./ui/dialog";
import { Kbd } from "./ui/misc";

function norm(s: string) {
  return s
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

const itemClass =
  "flex cursor-pointer items-center gap-3 rounded-md px-3 py-2.5 text-sm aria-selected:bg-primary-soft aria-selected:text-primary [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted aria-selected:[&_svg]:text-primary";
const groupClass =
  "px-1 pb-2 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted";

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const setCartOpen = useUi((s) => s.setCartOpen);
  const setAssistantOpen = useUi((s) => s.setAssistantOpen);
  const askAssistant = useAssistantChat((s) => s.send);
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query, 220);
  const search = useProductSearch(debounced);
  const orders = useOrders(useCustomerId(), 1, open);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        useUi.getState().setPaletteOpen(!useUi.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const run = (fn: () => void) => {
    setOpen(false);
    fn();
  };

  const actions = useMemo(
    () =>
      [
        { id: "loja", label: "Ir para a loja", icon: <Store />, run: () => navigate({ to: "/" }) },
        {
          id: "assistente",
          label: "Perguntar ao assistente",
          icon: <Sparkles />,
          run: () => setAssistantOpen(true),
        },
        {
          id: "carrinho",
          label: "Abrir carrinho",
          icon: <ShoppingBag />,
          run: () => setCartOpen(true),
        },
        {
          id: "pedidos",
          label: "Meus pedidos",
          icon: <ClipboardList />,
          run: () => navigate({ to: "/pedidos" }),
        },
        {
          id: "lojista",
          label: "Painel do lojista",
          icon: <Tag />,
          run: () => navigate({ to: "/lojista" }),
        },
        {
          id: "tema",
          label: theme === "dark" ? "Mudar para o tema claro" : "Mudar para o tema escuro",
          icon: theme === "dark" ? <Sun /> : <Moon />,
          run: toggle,
        },
      ].filter((a) => !query || norm(a.label).includes(norm(query))),
    [navigate, setCartOpen, setAssistantOpen, theme, toggle, query],
  );

  const products = query.trim() ? (search.data?.items ?? []) : [];
  const recentOrders = query.trim() ? [] : (orders.data?.items.slice(0, 3) ?? []);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        side="top"
        title="Paleta de comandos"
        description="Busque produtos e navegue"
        hideTitle
        className="p-0"
      >
        <Command shouldFilter={false} label="Buscar produtos ou ações" loop>
          <div className="flex items-center gap-3 border-b border-border px-4">
            <Search className="size-5 text-muted" aria-hidden />
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder="Buscar produtos ou ir para..."
              aria-label="Buscar produtos ou ações"
              className="h-14 flex-1 bg-transparent text-base outline-none placeholder:text-muted"
            />
            <Kbd>esc</Kbd>
          </div>
          <Command.List className="max-h-[min(60dvh,26rem)] overflow-y-auto p-2">
            {products.length > 0 && (
              <Command.Group heading="Produtos" className={groupClass}>
                {products.map((p) => (
                  <Command.Item
                    key={p.id}
                    value={`produto-${p.id}`}
                    className={itemClass}
                    onSelect={() =>
                      run(() => navigate({ to: "/produto/$slug", params: { slug: p.slug } }))
                    }
                  >
                    <Search />
                    <span className="flex-1 truncate">{p.name}</span>
                    <span className="tabular text-muted">{formatMoney(p.price_cents)}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {search.isFetching && query.trim() && products.length === 0 && (
              <p className="px-3 py-6 text-center text-sm text-muted">Buscando...</p>
            )}
            {query.trim() && (
              <Command.Group heading="Assistente" className={groupClass}>
                <Command.Item
                  value="perguntar-ao-assistente"
                  className={itemClass}
                  onSelect={() =>
                    run(() => {
                      setAssistantOpen(true);
                      void askAssistant(query);
                    })
                  }
                >
                  <Sparkles />
                  <span className="min-w-0 flex-1 truncate">Perguntar: {query.trim()}</span>
                </Command.Item>
              </Command.Group>
            )}
            {actions.length > 0 && (
              <Command.Group heading="Navegar" className={groupClass}>
                {actions.map((a) => (
                  <Command.Item
                    key={a.id}
                    value={a.id}
                    className={itemClass}
                    onSelect={() => run(a.run)}
                  >
                    {a.icon as ReactNode}
                    <span className="flex-1">{a.label}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {recentOrders.length > 0 && (
              <Command.Group heading="Pedidos recentes" className={groupClass}>
                {recentOrders.map((o) => (
                  <Command.Item
                    key={o.id}
                    value={`pedido-${o.id}`}
                    className={itemClass}
                    onSelect={() =>
                      run(() => navigate({ to: "/pedido/$id", params: { id: o.id } }))
                    }
                  >
                    <ClipboardList />
                    <span className="flex-1">Pedido {shortId(o.id)}</span>
                    <span className="tabular text-muted">{formatMoney(o.total_cents)}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
          <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-2 text-xs text-muted">
            <CornerDownLeft className="size-3.5" aria-hidden /> abrir
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
