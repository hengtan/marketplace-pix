import { Link, Outlet, useRouter, useRouterState } from "@tanstack/react-router";
import { ArrowUpRight, Moon, Search, ShoppingBag, Sun } from "lucide-react";
import {
  AnimatePresence,
  MotionConfig,
  motion,
  useMotionValueEvent,
  useReducedMotion,
  useScroll,
  useSpring,
} from "motion/react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Toaster, toast } from "sonner";
import { NotificationBell } from "@/components/notification-bell";
import { Kbd } from "@/components/ui/misc";
import { AssistantLauncher } from "@/features/assistant/launcher";
import { CART_BUTTON_ID } from "@/lib/fly";
import { EASE, SPRING, SPRING_POP } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { selectCount, useCart } from "@/store/cart";
import { useTheme } from "@/store/theme";
import { useUi } from "@/store/ui";
import { Cursor } from "./cursor";
import { UserMenu } from "./user-menu";
import { Wordmark } from "./wordmark";

const CartDrawer = lazy(() =>
  import("@/components/cart-drawer").then((m) => ({ default: m.CartDrawer })),
);
const CommandPalette = lazy(() =>
  import("@/components/command-palette").then((m) => ({ default: m.CommandPalette })),
);
const AssistantPanel = lazy(() =>
  import("@/features/assistant/panel").then((m) => ({ default: m.AssistantPanel })),
);

const NAV = [
  { to: "/", label: "Loja" },
  { to: "/pedidos", label: "Meus pedidos" },
  { to: "/lojista", label: "Lojista" },
] as const;

function isActive(to: string, pathname: string) {
  if (to === "/") return pathname === "/" || pathname.startsWith("/produto");
  if (to === "/pedidos") return pathname.startsWith("/pedido");
  return pathname.startsWith(to);
}

function CartCount({ count }: { count: number }) {
  return (
    <AnimatePresence mode="popLayout" initial={false}>
      {count > 0 && (
        <motion.span
          key={count}
          initial={{ scale: 0.2, y: 8, opacity: 0 }}
          animate={{ scale: 1, y: 0, opacity: 1 }}
          exit={{ scale: 0.2, y: -8, opacity: 0 }}
          transition={SPRING_POP}
          className="tabular absolute -top-1 -right-1 grid min-w-5 place-items-center rounded-full bg-pix px-1 text-[0.7rem] leading-5 font-bold text-[oklch(0.2_0.06_165)] shadow-[0_0_0_2px_var(--background)]"
        >
          {count}
        </motion.span>
      )}
    </AnimatePresence>
  );
}

function CartButton() {
  const count = useCart(selectCount);
  const bump = useUi((s) => s.cartBump);
  const setCartOpen = useUi((s) => s.setCartOpen);
  return (
    <motion.button
      key={bump}
      id={CART_BUTTON_ID}
      type="button"
      onClick={() => setCartOpen(true)}
      initial={bump > 0 ? { scale: 1 } : false}
      animate={bump > 0 ? { scale: [1, 1.22, 0.94, 1] } : undefined}
      transition={{ duration: 0.55, ease: EASE }}
      whileTap={{ scale: 0.92 }}
      className="relative grid size-11 place-items-center rounded-full bg-foreground text-background shadow-soft"
      aria-label={`Abrir carrinho, ${count} ${count === 1 ? "item" : "itens"}`}
    >
      <ShoppingBag className="size-5" />
      <CartCount count={count} />
    </motion.button>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <button
      type="button"
      onClick={toggle}
      className="relative grid size-11 place-items-center overflow-hidden rounded-full transition-colors hover:bg-surface-2"
      aria-label={theme === "dark" ? "Mudar para o tema claro" : "Mudar para o tema escuro"}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={theme}
          initial={{ rotate: -80, scale: 0.4, opacity: 0 }}
          animate={{ rotate: 0, scale: 1, opacity: 1 }}
          exit={{ rotate: 80, scale: 0.4, opacity: 0 }}
          transition={{ duration: 0.25, ease: EASE }}
          className="grid place-items-center"
        >
          {theme === "dark" ? <Sun className="size-5" /> : <Moon className="size-5" />}
        </motion.span>
      </AnimatePresence>
    </button>
  );
}

function Header() {
  const setPaletteOpen = useUi((s) => s.setPaletteOpen);
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);
  const reduce = useReducedMotion();
  const { scrollY, scrollYProgress } = useScroll();
  const progress = useSpring(scrollYProgress, { stiffness: 140, damping: 30, restDelta: 0.001 });
  const [scrolled, setScrolled] = useState(false);
  useMotionValueEvent(scrollY, "change", (v) => setScrolled(v > 12));

  return (
    <header
      className={cn(
        "sticky top-0 z-40 transition-[background-color,box-shadow,border-color] duration-500",
        scrolled
          ? "glass border-x-0 border-t-0 border-b-border shadow-[0_8px_30px_-18px_hsl(var(--shadow-color)/0.4)]"
          : "border-b border-transparent bg-transparent",
      )}
    >
      <div className="mx-auto flex h-[4.25rem] max-w-7xl items-center gap-2 px-4 sm:gap-4 sm:px-6">
        <Wordmark />
        <nav aria-label="Principal" className="ml-3 hidden items-center gap-0.5 md:flex">
          {NAV.map((n) => {
            const active = isActive(n.to, pathname);
            return (
              <Link
                key={n.to}
                to={n.to}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative rounded-full px-4 py-2 text-sm font-medium transition-colors",
                  active ? "text-primary" : "text-muted hover:text-foreground",
                )}
              >
                {active && (
                  <motion.span
                    layoutId="nav-pill"
                    className="absolute inset-0 -z-10 rounded-full bg-primary-soft"
                    transition={reduce ? { duration: 0 } : SPRING}
                  />
                )}
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-0.5 sm:gap-1">
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="group hidden h-11 items-center gap-3 rounded-full border border-border-strong/60 bg-surface/70 px-4 text-sm text-muted shadow-soft backdrop-blur transition-[border-color,color,box-shadow] hover:border-primary hover:text-foreground sm:flex"
          >
            <Search className="size-4 transition-transform duration-300 group-hover:scale-110" />
            <span className="w-24 text-left lg:w-36">Buscar</span>
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
          <ThemeToggle />
          <UserMenu />
          <CartButton />
        </div>
      </div>
      <nav
        aria-label="Principal (móvel)"
        className="hide-scrollbar flex gap-1 overflow-x-auto px-4 pb-2 md:hidden"
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
      {!reduce && (
        <motion.div
          aria-hidden
          className="absolute inset-x-0 bottom-0 h-[2px] origin-left bg-[linear-gradient(90deg,var(--primary),oklch(0.65_0.22_320),var(--sun))]"
          style={{ scaleX: progress }}
        />
      )}
    </header>
  );
}

function Footer() {
  return (
    <footer className="relative mt-28 overflow-hidden border-t border-border">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 pt-14 pb-10 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr]">
        <div className="grid content-start gap-4">
          <Wordmark />
          <p className="max-w-sm text-muted">
            Marketplace de estudo com checkout PIX de ponta a ponta. Nenhuma cobrança é real.
          </p>
        </div>
        <nav aria-label="Rodapé" className="grid content-start gap-2 text-sm">
          <p className="mb-1 font-semibold">Navegar</p>
          <Link to="/" className="w-fit text-muted hover:text-foreground">
            Loja
          </Link>
          <Link to="/pedidos" className="w-fit text-muted hover:text-foreground">
            Meus pedidos
          </Link>
          <Link to="/lojista" className="w-fit text-muted hover:text-foreground">
            Painel do lojista
          </Link>
        </nav>
        <div className="grid content-start gap-2 text-sm">
          <p className="mb-1 font-semibold">Como funciona</p>
          <p className="text-muted">Estoque reservado ao criar o pedido.</p>
          <p className="text-muted">PIX com confirmação em tempo real.</p>
          <p className="text-muted">Livro-razão conciliado para o lojista.</p>
        </div>
      </div>
      <div
        aria-hidden
        className="pointer-events-none -mb-[0.2em] select-none text-center font-display text-[clamp(6rem,24vw,22rem)] leading-[0.8] font-bold tracking-[-0.06em] text-transparent [-webkit-text-stroke:1px_var(--border-strong)]"
      >
        Praça
      </div>
      <div className="relative border-t border-border bg-background/60">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-5 text-sm text-muted sm:px-6">
          <span>Praça, projeto de estudo.</span>
          <a
            href="https://mocktstudio.com"
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-1.5 font-medium text-foreground"
          >
            Engineering by MocktStudio
            <ArrowUpRight className="size-4 transition-transform duration-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
          </a>
        </div>
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
  const assistantOpen = useUi((s) => s.assistantOpen);
  const cartOpen = useUi((s) => s.cartOpen);
  const paletteOpen = useUi((s) => s.paletteOpen);
  const [assistantReady, setAssistantReady] = useState(false);
  const [cartReady, setCartReady] = useState(false);
  const [paletteReady, setPaletteReady] = useState(false);

  useEffect(() => {
    if (assistantOpen) setAssistantReady(true);
    if (cartOpen) setCartReady(true);
    if (paletteOpen) setPaletteReady(true);
  }, [assistantOpen, cartOpen, paletteOpen]);

  const paletteLoaded = useRef(false);
  paletteLoaded.current = paletteReady;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k" && !paletteLoaded.current) {
        e.preventDefault();
        setPaletteReady(true);
        useUi.getState().setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  useEffect(() => {
    const idle = (window.requestIdleCallback ?? ((cb: () => void) => setTimeout(cb, 2500)))(() => {
      setAssistantReady(true);
      setCartReady(true);
      setPaletteReady(true);
    });
    return () => {
      if (typeof idle === "number" && window.cancelIdleCallback) window.cancelIdleCallback(idle);
    };
  }, []);

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
    <MotionConfig reducedMotion="user">
      <a
        href="#conteudo"
        className="sr-only z-[100] rounded-full bg-foreground px-5 py-2.5 text-background focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Pular para o conteúdo
      </a>
      <Header />
      <main id="conteudo" ref={mainRef} tabIndex={-1} className="outline-none">
        <motion.div
          key={pathname}
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.55, ease: EASE }}
        >
          <Outlet />
        </motion.div>
      </main>
      <Footer />
      <Suspense fallback={null}>
        {cartReady && <CartDrawer />}
        {paletteReady && <CommandPalette />}
      </Suspense>
      <AssistantLauncher />
      {assistantReady && (
        <Suspense fallback={null}>
          <AssistantPanel />
        </Suspense>
      )}
      <Cursor />
      <Toaster
        position="bottom-right"
        offset={{ right: 24, bottom: 92 }}
        mobileOffset={{ right: 16, bottom: 84 }}
        theme={toastTheme}
        style={
          {
            "--normal-bg": "var(--glass)",
            "--normal-border": "var(--border-strong)",
            "--normal-text": "var(--foreground)",
            "--border-radius": "1.1rem",
          } as React.CSSProperties
        }
        toastOptions={{ className: "!backdrop-blur-xl !shadow-lift" }}
      />
    </MotionConfig>
  );
}
