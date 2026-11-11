import { useMemo } from "react";
import { useMerchantOrders, useMerchantProducts, useMerchantStock } from "@/hooks/merchant";
import { buildStockRows, dailySalesRate } from "@/lib/merchant-metrics";
import { useMerchant } from "./context";

export function useStockRows() {
  const { merchantId, ownsStore } = useMerchant();
  const products = useMerchantProducts(merchantId);
  const activeProducts = useMemo(
    () => (products.data ?? []).filter((p) => p.active),
    [products.data],
  );
  const inactiveProducts = useMemo(
    () => (products.data ?? []).filter((p) => !p.active),
    [products.data],
  );
  const stock = useMerchantStock(merchantId, ownsStore, activeProducts);
  const orders = useMerchantOrders(ownsStore);

  const productMap = useMemo(() => new Map(activeProducts.map((p) => [p.id, p])), [activeProducts]);
  const rows = useMemo(() => {
    if (!stock.data) return undefined;
    const known = stock.data.filter((s) => productMap.has(s.product_id));
    return buildStockRows(known, dailySalesRate(orders.data?.items ?? [], Date.now()));
  }, [stock.data, productMap, orders.data]);

  return { products, activeProducts, inactiveProducts, stock, orders, rows, productMap };
}
