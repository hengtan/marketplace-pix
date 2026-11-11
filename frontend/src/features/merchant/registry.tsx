import type { ComponentType } from "react";
import { lazyReload } from "@/lib/lazy-reload";
import type { MerchantTab } from "@/lib/merchant-metrics";

const Overview = lazyReload(() => import("./overview").then((m) => ({ default: m.Overview })));

export const TAB_VIEWS: Partial<Record<MerchantTab, ComponentType>> = {
  "visao-geral": Overview,
};
