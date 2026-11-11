import { useNavigate } from "@tanstack/react-router";
import { createContext, useContext, useMemo } from "react";
import type { MerchantTab } from "@/lib/merchant-metrics";

export interface MerchantCtx {
  merchantId: string;
  merchantName: string;
  days: number;
  tab: MerchantTab;
  ownsStore: boolean;
  isAdmin: boolean;
  fresh: ReadonlySet<string>;
  openOrderId: string | undefined;
  creatingProduct: boolean;
}

const Ctx = createContext<MerchantCtx | null>(null);

export const MerchantProvider = Ctx.Provider;

export function useMerchant(): MerchantCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useMerchant must be used inside the merchant panel");
  return ctx;
}

export function useMerchantNav() {
  const navigate = useNavigate({ from: "/lojista" });
  return useMemo(
    () => ({
      go: (tab: MerchantTab) =>
        navigate({ search: (prev) => ({ ...prev, aba: tab, pedido: undefined, novo: undefined }) }),
      setDays: (dias: number) =>
        navigate({ search: (prev) => ({ ...prev, dias }), replace: true, resetScroll: false }),
      setStore: (loja: string) =>
        navigate({ search: (prev) => ({ ...prev, loja }), replace: true, resetScroll: false }),
      openOrder: (pedido: string) =>
        navigate({ search: (prev) => ({ ...prev, aba: "pedidos", pedido }), resetScroll: false }),
      closeOrder: () =>
        navigate({
          search: (prev) => ({ ...prev, pedido: undefined }),
          replace: true,
          resetScroll: false,
        }),
      newProduct: () =>
        navigate({
          search: (prev) => ({ ...prev, aba: "produtos", novo: true }),
          resetScroll: false,
        }),
      closeNewProduct: () =>
        navigate({
          search: (prev) => ({ ...prev, novo: undefined }),
          replace: true,
          resetScroll: false,
        }),
    }),
    [navigate],
  );
}
