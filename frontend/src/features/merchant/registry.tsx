import type { ComponentType } from "react";
import { lazyReload } from "@/lib/lazy-reload";
import type { MerchantTab } from "@/lib/merchant-metrics";

const Overview = lazyReload(() => import("./overview").then((m) => ({ default: m.Overview })));
const Orders = lazyReload(() => import("./orders").then((m) => ({ default: m.Orders })));
const Stock = lazyReload(() => import("./stock").then((m) => ({ default: m.Stock })));
const Products = lazyReload(() => import("./products").then((m) => ({ default: m.Products })));

export const TAB_VIEWS: Partial<Record<MerchantTab, ComponentType>> = {
  "visao-geral": Overview,
  pedidos: Orders,
  estoque: Stock,
  produtos: Products,
};
