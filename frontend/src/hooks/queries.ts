import {
  keepPreviousData,
  type QueryClient,
  useInfiniteQuery,
  useQuery,
} from "@tanstack/react-query";
import { api, type ProductFilters } from "@/api/endpoints";
import { useAuth } from "@/store/auth";

export const qk = {
  products: (f: ProductFilters) => ["products", f] as const,
  product: (slug: string) => ["product", slug] as const,
  categories: ["categories"] as const,
  stock: (ids: string[]) => ["stock", [...ids].sort().join(",")] as const,
  order: (id: string) => ["order", id] as const,
  payment: (orderId: string) => ["payment", orderId] as const,
  orders: (customerId: string, page: number) => ["orders", customerId, page] as const,
  notifications: (customerId: string) => ["notifications", customerId] as const,
  summary: (merchantId: string, days: number) => ["summary", merchantId, days] as const,
  entries: (merchantId: string, page: number) => ["entries", merchantId, page] as const,
  reconciliation: ["reconciliation"] as const,
};

export function useProductsInfinite(filters: Omit<ProductFilters, "page">) {
  return useInfiniteQuery({
    queryKey: ["products", "infinite", filters],
    queryFn: ({ pageParam, signal }) => api.products({ ...filters, page: pageParam }, signal),
    initialPageParam: 1,
    getNextPageParam: (last) =>
      last.page * last.page_size < last.total ? last.page + 1 : undefined,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

export function useProductSearch(q: string) {
  return useQuery({
    queryKey: qk.products({ q, page_size: 6 }),
    queryFn: ({ signal }) => api.products({ q, page_size: 6 }, signal),
    enabled: q.trim().length > 0,
    staleTime: 30_000,
  });
}

export function useProduct(slug: string) {
  return useQuery({
    queryKey: qk.product(slug),
    queryFn: () => api.productBySlug(slug),
    staleTime: 60_000,
  });
}

export function useCategories() {
  return useQuery({
    queryKey: qk.categories,
    queryFn: api.categories,
    staleTime: 5 * 60_000,
  });
}

export function useStock(ids: string[]) {
  return useQuery({
    queryKey: qk.stock(ids),
    queryFn: () => api.stock(ids),
    enabled: ids.length > 0,
    staleTime: 10_000,
    select: (rows) => Object.fromEntries(rows.map((r) => [r.product_id, r.available])),
  });
}

export function useRelatedProducts(
  category: string | undefined,
  excludeId: string | undefined,
  ready = true,
) {
  return useQuery({
    queryKey: ["related", category, excludeId],
    queryFn: () => api.products({ category, sort: "rating", page_size: 5 }),
    enabled: Boolean(category) && ready,
    staleTime: 60_000,
    select: (page) => page.items.filter((p) => p.id !== excludeId).slice(0, 4),
  });
}

export function prefetchProduct(client: QueryClient, slug: string) {
  return client.prefetchQuery({
    queryKey: qk.product(slug),
    queryFn: () => api.productBySlug(slug),
    staleTime: 60_000,
  });
}

export function useOrders(customerId: string, page: number, enabled = true) {
  return useQuery({
    enabled,
    queryKey: qk.orders(customerId, page),
    queryFn: () => api.orders(customerId, page, 8),
    placeholderData: keepPreviousData,
    staleTime: 0,
  });
}

export function useNotifications(customerId: string) {
  const signedIn = useAuth((s) => Boolean(s.accessToken));
  return useQuery({
    queryKey: qk.notifications(customerId),
    queryFn: () => api.notifications(customerId, 1, 20),
    enabled: signedIn,
    refetchInterval: signedIn ? 15_000 : false,
    staleTime: 5_000,
  });
}

export function useMerchantSummary(merchantId: string, days: number) {
  return useQuery({
    queryKey: qk.summary(merchantId, days),
    queryFn: () => api.merchantSummary(merchantId, days),
    staleTime: 15_000,
  });
}

export function useMerchantEntries(merchantId: string, page: number) {
  return useQuery({
    queryKey: qk.entries(merchantId, page),
    queryFn: () => api.merchantEntries(merchantId, page, 8),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useReconciliation() {
  return useQuery({
    queryKey: qk.reconciliation,
    queryFn: api.reconciliation,
    staleTime: 15_000,
  });
}
