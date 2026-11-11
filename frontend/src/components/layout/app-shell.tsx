import { Link, Outlet, useRouter, useRouterState } from "@tanstack/react-router";
import { Moon, Search, ShoppingBag, Sun } from "lucide-react";
import { useEffect, useRef } from "react";
import { Toaster, toast } from "sonner";
import { CartDrawer } from "@/components/cart-drawer";
import { CommandPalette } from "@/components/command-palette";
import { NotificationBell } from "@/components/notification-bell";
import { Kbd } from "@/components/ui/misc";
import { cn } from "@/lib/utils";
import { selectCount, useCart } from "@/store/cart";
import { useTheme } from "@/store/theme";
import { useUi } from "@/store/ui";

function Wordmark() {
  return (
    <Link to="/" className="flex items-center gap-2 rounded-md" aria-label="Praça, página inicial">
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="9" className="fill-primary" />
        <path
          d="M10 23V9h7a4.5 4.5 0 0 1 0 9h-3"
          fill="none"
          className="stroke-primary-foreground"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="23" cy="22" r="2.2" className="fill-pix" />
      </svg>
      <span className="font-display text-2xl font-bold tracking-tight">Praça</span>
    </Link>
  );
}

const NAV = [
  { to: "/", label: "Loja" },
  { to: "/pedidos", label: "Meus pedidos" },
  { to: "/lojista", label: "Lojista" },
] as const;

function Header() {
  const { theme, toggle } = useTheme();
  const count = useCart(selectCount);
  const setCartOpen = useUi((s) => s.setCartOpen);
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/85 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-7xl items-center gap-2 px-4 sm:gap-4 sm:px-6">
        <Wordmark />
        <nav aria-label="Principal" className="ml-2 hidden items-center gap-1 md:flex">
          {NAV.map((n) => {
            const active =
              n.to === "/"
                ? pathname === "/" || pathname.startsWith("/produto")
                : pathname.startsWith(n.to) ||
                  (n.to === "/pedidos" && pathname.startsWith("/pedido"));
            return (
              <Link
                key={n.to}
                to={n.to}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-full px-4 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-primary-soft text-primary"
                    : "text-muted hover:bg-surface-2 hover:text-foreground",
                )}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="hidden h-11 items-center gap-3 rounded-full border border-border bg-surface px-4 text-sm text-muted transition-colors hover:border-primary hover:text-foreground sm:flex"
          >
            <Search className="size-4" />
            <span className="w-28 text-left lg:w-40">Buscar</span>
            <Kbd>{isMac ? "⌘K" : "Ctrl K"}</Kbd>
          </button>
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="grid size-11 place-items-center rounded-full hover:bg-surface-2 sm:hidden"
            aria-label="Buscar"
          >
            <Search className="size-5" />
          </button>
          <NotificationBell />
          <button
            type="button"
            onClick={toggle}
            className="grid size-11 place-items-center rounded-full transition-colors hover:bg-surface-2"
            aria-label={theme === "dark" ? "Mudar para o tema claro" : "Mudar para o tema escuro"}
          >
            {theme === "dark" ? <Sun className="size-5" /> : <Moon className="size-5" />}
          </button>
          <button
            type="button"
            onClick={() => setCartOpen(true)}
            className="relative grid size-11 place-items-center rounded-full bg-foreground text-background transition-transform active:scale-95"
            aria-label={`Abrir carrinho, ${count} ${count === 1 ? "item" : "itens"}`}
          >
            <ShoppingBag className="size-5" />
            {count > 0 && (
              <span
                key={count}
                className="tabular absolute -top-1 -right-1 grid min-w-5 animate-in zoom-in-50 place-items-center rounded-full bg-pix px-1 text-[0.7rem] leading-5 font-bold text-[oklch(0.2_0.06_165)] ring-2 ring-background"
              >
                {count}
              </span>
            )}
          </button>
        </div>
      </div>
      <nav
        aria-label="Principal (móvel)"
        className="flex gap-1 overflow-x-auto px-4 pb-2 md:hidden"
      >
        {NAV.map((n) => (
          <Link
            key={n.to}
            to={n.to}
            activeOptions={{ exact: n.to === "/" }}
            className="rounded-full px-4 py-2 text-sm font-medium whitespace-nowrap text-muted data-[status=active]:bg-primary-soft data-[status=active]:text-primary"
          >
            {n.label}
          </Link>
        ))}
      </nav>
    </header>
  );
}

function Footer() {
  return (
    <footer className="mt-24 border-t border-border">
      <div className="mx-auto flex max-w-7xl flex-col gap-3 px-4 py-10 text-sm text-muted sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <Wordmark />
        <p>Projeto de estudo de marketplace com checkout PIX. Nenhuma cobrança é real.</p>
      </div>
    </footer>
  );
}

export function AppShell() {
  const toastTheme = useTheme((s) => s.theme);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const router = useRouter();
  const mainRef = useRef<HTMLElement>(null);
  const first = useRef(true);

  useEffect(
    () =>
      router.subscribe("onResolved", () => {
        if (first.current) {
          first.current = false;
          return;
        }
        toast.dismiss();
        window.scrollTo({ top: 0 });
        mainRef.current?.focus({ preventScroll: true });
      }),
    [router],
  );

  return (
    <>
      <a
        href="#conteudo"
        className="sr-only z-[100] rounded-md bg-foreground px-4 py-2 text-background focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Pular para o conteúdo
      </a>
      <Header />
      <main id="conteudo" ref={mainRef} tabIndex={-1} className="outline-none">
        <div key={pathname} className="animate-in fade-in-0 slide-in-from-bottom-1 duration-500">
          <Outlet />
        </div>
      </main>
      <Footer />
      <CartDrawer />
      <CommandPalette />
      <Toaster position="bottom-right" offset={24} theme={toastTheme} />
    </>
  );
}
