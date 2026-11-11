import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  lazyRouteComponent,
  redirect,
} from "@tanstack/react-router";
import * as z from "zod/mini";
import { AppShell } from "@/components/layout/app-shell";
import { EmptyState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { restoreSession } from "@/features/session";
import { beginExit, shouldAnimateExit } from "@/lib/route-transition";
import { setSessionExpiredHandler } from "@/lib/session";
import { toast } from "@/lib/toast";
import { isSignedIn } from "@/store/auth";
import HomePage from "./pages/home";
import ProductPage from "./pages/product";

const homeSearch = z.object({
  q: z.optional(z.string()),
  categoria: z.optional(z.string()),
  preco: z.optional(z.enum(["ate-100", "100-300", "300-mais"])),
  ordem: z.optional(z.enum(["relevance", "price_asc", "price_desc", "newest", "rating"])),
});

function NotFound() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <EmptyState
        art="lost"
        title="Página não encontrada"
        description="O endereço não existe ou foi movido."
        action={
          <Button asChild>
            <Link to="/">Voltar para a loja</Link>
          </Button>
        }
      />
    </div>
  );
}

const rootRoute = createRootRoute({
  component: AppShell,
  notFoundComponent: NotFound,
  beforeLoad: ({ location, preload }) => {
    if (preload) return;
    const from = router.state.resolvedLocation?.pathname;
    if (shouldAnimateExit(from, location.pathname)) return beginExit();
  },
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: homeSearch,
  component: HomePage,
});
const productRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/produto/$slug",
  component: ProductPage,
});
const checkoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/checkout",
  component: lazyRouteComponent(() => import("./pages/checkout")),
});
const orderRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pedido/$id",
  component: lazyRouteComponent(() => import("./pages/order")),
});
const ordersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pedidos",
  component: lazyRouteComponent(() => import("./pages/orders")),
});
const authSearch = z.object({ redirect: z.optional(z.string()) });

async function requireSession({ location }: { location: { href: string } }) {
  await restoreSession();
  if (!isSignedIn()) throw redirect({ to: "/entrar", search: { redirect: location.href } });
}

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/entrar",
  validateSearch: authSearch,
  component: lazyRouteComponent(() => import("./pages/auth"), "LoginPage"),
});
const registerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/cadastro",
  validateSearch: authSearch,
  component: lazyRouteComponent(() => import("./pages/auth"), "RegisterPage"),
});
const accountRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/conta",
  beforeLoad: requireSession,
  component: lazyRouteComponent(() => import("./pages/account")),
});
const merchantRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/lojista",
  beforeLoad: requireSession,
  component: lazyRouteComponent(() => import("./pages/merchant")),
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  productRoute,
  checkoutRoute,
  orderRoute,
  ordersRoute,
  merchantRoute,
  loginRoute,
  registerRoute,
  accountRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  scrollRestoration: true,
});

const PROTECTED_PREFIXES = ["/conta", "/lojista"];

setSessionExpiredHandler(() => {
  const { pathname, href } = router.state.location;
  void toast.message("Sua sessão expirou", { description: "Entre de novo para continuar." });
  if (PROTECTED_PREFIXES.some((p) => pathname.startsWith(p))) {
    void router.navigate({ to: "/entrar", search: { redirect: href } });
  }
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
