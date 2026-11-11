import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { domMax, LazyMotion } from "motion/react";
import type { ReactElement, ReactNode } from "react";

export function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
}

export function wrapper(client = makeClient()) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

export async function renderWithRouter(ui: ReactElement, client = makeClient()) {
  const root = createRootRoute({ component: () => ui });
  const paths = ["/produto/$slug", "/checkout", "/"].map((path) =>
    createRoute({ getParentRoute: () => root, path, component: () => null }),
  );
  const router = createRouter({
    routeTree: root.addChildren(paths),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  const utils = render(
    <LazyMotion features={domMax} strict>
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </LazyMotion>,
  );
  return { ...utils, router };
}
