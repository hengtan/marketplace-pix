import { useMemo } from "react";
import { useMerchantOrders, useMerchantProducts, useMerchantStock } from "@/hooks/merchant";
import { buildStockRows, dailySalesRate } from "@/lib/merchant-metrics";
import { useMerchant } from "./context";

export function useStockRows() {
  const { merchantId, ownsStore } = useMerchant();
  const products = useMerchantProducts(merchantId);
  const stock = useMerchantStock(merchantId, ownsStore, products.data);
  const orders = useMerchantOrders(ownsStore);

  const productMap = useMemo(
    () => new Map((products.data ?? []).map((p) => [p.id, p])),
    [products.data],
  );
  const rows = useMemo(() => {
    if (!stock.data) return undefined;
    const known = stock.data.filter((s) => productMap.has(s.product_id));
    return buildStockRows(known, dailySalesRate(orders.data?.items ?? [], Date.now()));
  }, [stock.data, productMap, orders.data]);

  return { products, stock, orders, rows, productMap };
}
