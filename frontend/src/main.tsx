import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { env } from "@/lib/env";
import "./index.css";
import { router } from "./router";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
});

async function enableMocks() {
  if (!env.useMocks) return;
  const { worker } = await import("./mocks/browser");
  await worker.start({ onUnhandledFrame: "bypass", quiet: true });
}

enableMocks().then(() => {
  const root = document.getElementById("root");
  if (!root) throw new Error("Root element not found");
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </StrictMode>,
  );
});
