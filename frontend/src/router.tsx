import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Link,
} from "@tanstack/react-router";
import { z } from "zod";
import { AppShell } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/states";

const homeSearch = z.object({
  q: z.string().optional(),
  categoria: z.string().optional(),
  preco: z.enum(["ate-100", "100-300", "300-mais"]).optional(),
  ordem: z.enum(["relevance", "price_asc", "price_desc", "newest", "rating"]).optional(),
});

function NotFound() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
      <EmptyState
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

const rootRoute = createRootRoute({ component: AppShell, notFoundComponent: NotFound });

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: homeSearch,
  component: lazyRouteComponent(() => import("./pages/home")),
});
const productRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/produto/$slug",
  component: lazyRouteComponent(() => import("./pages/product")),
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
const merchantRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/lojista",
  component: lazyRouteComponent(() => import("./pages/merchant")),
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  productRoute,
  checkoutRoute,
  orderRoute,
  ordersRoute,
  merchantRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
