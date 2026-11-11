import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { restoreSession } from "@/features/session";
import { env } from "@/lib/env";
import { clearReloadFlag } from "@/lib/lazy-reload";
import { afterFirstPaint } from "@/lib/shell";
import "./index.css";

import("@/lib/motion-features");

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

Promise.all([enableMocks(), afterFirstPaint()]).then(() => {
  void restoreSession();
  clearReloadFlag();
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
