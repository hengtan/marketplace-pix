import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import { merchantApi, type NewProductInput, type ProductPatch } from "@/api/merchant";
import type { OwnProduct, Product, Stock } from "@/api/schemas";
import { writeErrorMessage } from "@/lib/merchant-errors";
import { toast } from "@/lib/toast";
import { useAuth } from "@/store/auth";

export const ORDERS_POLL_MS = 10_000;

const CATALOG_SETTLE_MS = 3_000;

function settleLater(run: () => void) {
  setTimeout(run, CATALOG_SETTLE_MS);
}

export const mk = {
  orders: ["merchant-orders"] as const,
  products: (merchantId: string) => ["merchant-products", merchantId] as const,
  stock: (merchantId: string) => ["merchant-stock", merchantId] as const,
  ledger: (merchantId: string) => ["merchant-ledger", merchantId] as const,
};

export function useMerchantOrders(enabled: boolean) {
  return useQuery({
    queryKey: mk.orders,
    queryFn: merchantApi.merchantOrders,
    enabled,
    refetchInterval: ORDERS_POLL_MS,
    staleTime: 5_000,
  });
}

export function useMerchantProducts(merchantId: string) {
  return useQuery({
    queryKey: mk.products(merchantId),
    queryFn: ({ signal }) => merchantApi.merchantProducts(merchantId, signal),
    staleTime: 15_000,
  });
}

export function useMerchantStock(
  merchantId: string,
  ownsStore: boolean,
  products: Product[] | undefined,
) {
  const ids = products?.map((p) => p.id) ?? [];
  const ready = ownsStore || ids.length > 0;
  return useQuery({
    queryKey: mk.stock(merchantId),
    queryFn: (): Promise<Stock[]> => (ownsStore ? merchantApi.myStock() : api.stock(ids)),
    enabled: ready,
    refetchInterval: 20_000,
    staleTime: 8_000,
  });
}

export function useMerchantLedger(merchantId: string) {
  return useQuery({
    queryKey: mk.ledger(merchantId),
    queryFn: () => merchantApi.merchantEntriesAll(merchantId),
    staleTime: 15_000,
  });
}

export function useOwnsStore() {
  const user = useAuth((s) => s.user);
  return Boolean(user?.merchant_id) && !user?.roles.includes("admin");
}

export function useUpdateStock(merchantId: string) {
  const client = useQueryClient();
  const key = mk.stock(merchantId);
  return useMutation({
    mutationFn: ({ productId, available }: { productId: string; available: number }) =>
      merchantApi.setStock(productId, available),
    onMutate: async ({ productId, available }) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<Stock[]>(key);
      client.setQueryData<Stock[]>(key, (rows) =>
        rows?.map((r) => (r.product_id === productId ? { ...r, available } : r)),
      );
      return { previous };
    },
    onError: (error, _vars, ctx) => {
      if (ctx?.previous) client.setQueryData(key, ctx.previous);
      void toast.error("Estoque não alterado", {
        description: writeErrorMessage(error, "estoque"),
      });
    },
    onSettled: () => {
      void client.invalidateQueries({ queryKey: key });
      void client.invalidateQueries({ queryKey: ["stock"] });
    },
  });
}

export function useCreateProduct(merchantId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (input: NewProductInput) => merchantApi.createProduct(input),
    onSuccess: (product) => {
      client.setQueryData<OwnProduct[]>(mk.products(merchantId), (rows) => [
        { ...product, active: true },
        ...(rows ?? []),
      ]);
      settleLater(() => {
        void client.invalidateQueries({ queryKey: mk.products(merchantId) });
        void client.invalidateQueries({ queryKey: mk.stock(merchantId) });
        void client.invalidateQueries({ queryKey: ["products"] });
        void client.invalidateQueries({ queryKey: ["categories"] });
      });
    },
  });
}

export function useUpdateProduct(merchantId: string) {
  const client = useQueryClient();
  const key = mk.products(merchantId);
  return useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: ProductPatch }) =>
      merchantApi.updateProduct(id, patch),
    onMutate: async ({ id, patch }) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<OwnProduct[]>(key);
      client.setQueryData<OwnProduct[]>(key, (rows) =>
        rows?.map((p) => (p.id === id ? { ...p, ...patch } : p)),
      );
      return { previous };
    },
    onSuccess: (product) => {
      client.setQueryData<OwnProduct[]>(key, (rows) =>
        rows?.map((p) => (p.id === product.id ? { ...product, active: p.active } : p)),
      );
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) client.setQueryData(key, ctx.previous);
    },
    onSettled: () => {
      settleLater(() => {
        void client.invalidateQueries({ queryKey: key });
        void client.invalidateQueries({ queryKey: ["products"] });
        void client.invalidateQueries({ queryKey: ["product"] });
      });
    },
  });
}

export function useDeactivateProduct(merchantId: string) {
  const client = useQueryClient();
  const key = mk.products(merchantId);
  return useMutation({
    mutationFn: (id: string) => merchantApi.deactivateProduct(id),
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<OwnProduct[]>(key);
      client.setQueryData<OwnProduct[]>(key, (rows) =>
        rows?.map((p) => (p.id === id ? { ...p, active: false } : p)),
      );
      return { previous };
    },
    onError: (error, _id, ctx) => {
      if (ctx?.previous) client.setQueryData(key, ctx.previous);
      void toast.error("Produto não desativado", {
        description: writeErrorMessage(error, "catálogo"),
      });
    },
    onSettled: () => {
      settleLater(() => {
        void client.invalidateQueries({ queryKey: key });
        void client.invalidateQueries({ queryKey: mk.stock(merchantId) });
        void client.invalidateQueries({ queryKey: ["products"] });
      });
    },
  });
}

export function useReactivateProduct(merchantId: string) {
  const client = useQueryClient();
  const key = mk.products(merchantId);
  return useMutation({
    mutationFn: (id: string) => merchantApi.reactivateProduct(id),
    onMutate: async (id) => {
      await client.cancelQueries({ queryKey: key });
      const previous = client.getQueryData<OwnProduct[]>(key);
      client.setQueryData<OwnProduct[]>(key, (rows) =>
        rows?.map((p) => (p.id === id ? { ...p, active: true } : p)),
      );
      return { previous };
    },
    onError: (error, _id, ctx) => {
      if (ctx?.previous) client.setQueryData(key, ctx.previous);
      void toast.error("Produto não reativado", {
        description: writeErrorMessage(error, "catálogo"),
      });
    },
    onSettled: () => {
      settleLater(() => {
        void client.invalidateQueries({ queryKey: key });
        void client.invalidateQueries({ queryKey: mk.stock(merchantId) });
        void client.invalidateQueries({ queryKey: ["products"] });
      });
    },
  });
}
