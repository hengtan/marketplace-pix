import * as z from "zod/mini";
import { ApiError, request } from "./client";
import {
  type LedgerEntry,
  ledgerEntryPageSchema,
  type OwnProduct,
  orderItemSchema,
  ownProductListSchema,
  paged,
  productPageSchema,
  productSchema,
  stockSchema,
} from "./schemas";

export const merchantOrderSchema = z.object({
  id: z.string(),
  status: z.string(),
  currency: z.string(),
  created_at: z.string(),
  customer_name: z.string(),
  subtotal_cents: z.int(),
  items: z.array(orderItemSchema),
});
export type MerchantOrder = z.infer<typeof merchantOrderSchema>;
export const merchantOrderPageSchema = paged(merchantOrderSchema);

export interface NewProductInput {
  name: string;
  description: string;
  price_cents: number;
  category: string;
  tags?: string[];
  image_url?: string | null;
  merchant_id?: string;
}

export interface ProductPatch {
  name?: string;
  description?: string;
  price_cents?: number;
  category?: string;
  tags?: string[];
}

const MAX_PAGES = 4;

async function publicProducts(merchantId: string, signal?: AbortSignal): Promise<OwnProduct[]> {
  const found: OwnProduct[] = [];
  for (let page = 1; page <= MAX_PAGES; page++) {
    const res = await request("/api/catalog/products", {
      schema: productPageSchema,
      query: { page, page_size: 48, sort: "newest" },
      signal,
    });
    found.push(
      ...res.items.filter((p) => p.merchant.id === merchantId).map((p) => ({ ...p, active: true })),
    );
    if (page * res.page_size >= res.total) break;
  }
  return found;
}

export const merchantApi = {
  merchantProducts: async (merchantId: string, signal?: AbortSignal): Promise<OwnProduct[]> => {
    try {
      const res = await request("/api/catalog/products/mine", {
        schema: ownProductListSchema,
        query: { merchant_id: merchantId },
        signal,
      });
      return res.items;
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 403) throw error;
      return publicProducts(merchantId, signal);
    }
  },
  reactivateProduct: (id: string) =>
    request(`/api/catalog/products/${id}/reactivate`, { schema: productSchema, method: "POST" }),
  createProduct: (input: NewProductInput) =>
    request("/api/catalog/products", {
      schema: productSchema,
      method: "POST",
      body: input,
    }),
  updateProduct: (id: string, patch: ProductPatch) =>
    request(`/api/catalog/products/${id}`, {
      schema: productSchema,
      method: "PATCH",
      body: patch,
    }),
  deactivateProduct: (id: string) =>
    request(`/api/catalog/products/${id}`, { schema: z.null(), method: "DELETE" }),

  myStock: () => request("/api/inventory/stock/mine", { schema: z.array(stockSchema) }),
  setStock: (productId: string, available: number) =>
    request(`/api/inventory/stock/${productId}`, {
      schema: stockSchema,
      method: "PUT",
      body: { available },
    }),

  merchantEntriesAll: async (merchantId: string) => {
    const found: LedgerEntry[] = [];
    for (let page = 1; page <= MAX_PAGES; page++) {
      const res = await request(`/api/ledger/accounts/merchant:${merchantId}/entries`, {
        schema: ledgerEntryPageSchema,
        query: { page, page_size: 100 },
      });
      found.push(...res.items);
      if (page * res.page_size >= res.total) return { items: found, total: res.total };
    }
    return { items: found, total: found.length };
  },
  merchantOrders: async () => {
    const found: MerchantOrder[] = [];
    for (let page = 1; page <= MAX_PAGES; page++) {
      const res = await request("/api/orders/merchant", {
        schema: merchantOrderPageSchema,
        query: { page, page_size: 50 },
      });
      found.push(...res.items);
      if (page * res.page_size >= res.total) return { items: found, total: res.total };
    }
    return { items: found, total: found.length };
  },
};
