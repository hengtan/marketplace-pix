import type { ComponentType } from "react";
import { lazyReload } from "@/lib/lazy-reload";
import type { MerchantTab } from "@/lib/merchant-metrics";

const Overview = lazyReload(() => import("./overview").then((m) => ({ default: m.Overview })));
const Orders = lazyReload(() => import("./orders").then((m) => ({ default: m.Orders })));

export const TAB_VIEWS: Partial<Record<MerchantTab, ComponentType>> = {
  "visao-geral": Overview,
  pedidos: Orders,
};
