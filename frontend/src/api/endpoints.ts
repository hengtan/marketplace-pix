import * as z from "zod/mini";
import { ApiError, authedFetch, buildUrl, parseRetryAfter, request, toError } from "./client";
import {
  categorySchema,
  createOrderResponseSchema,
  type LedgerEntry,
  ledgerEntryPageSchema,
  type MerchantOrder,
  merchantOrderPageSchema,
  merchantSummarySchema,
  notificationPageSchema,
  orderPageSchema,
  orderSchema,
  type Payment,
  type Product,
  paymentSchema,
  productPageSchema,
  productSchema,
  reconciliationSchema,
  stockSchema,
  tokenResponseSchema,
  userSchema,
} from "./schemas";

export type ProductSort = "relevance" | "price_asc" | "price_desc" | "newest" | "rating";

export interface ProductFilters {
  q?: string;
  category?: string;
  min_price_cents?: number;
  max_price_cents?: number;
  sort?: ProductSort;
  page?: number;
  page_size?: number;
}

export interface CreateOrderInput {
  customer_id: string;
  customer_name: string;
  customer_email: string;
  items: { product_id: string; quantity: number }[];
}

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

export interface RegisterInput {
  name: string;
  email: string;
  password: string;
}

export interface PaymentPending {
  pending: true;
  retryAfter?: number;
}

export const isPaymentPending = (p: Payment | PaymentPending | undefined): p is PaymentPending =>
  p !== undefined && "pending" in p;

export const api = {
  register: (input: RegisterInput) =>
    request("/api/auth/register", {
      schema: tokenResponseSchema,
      method: "POST",
      body: input,
      auth: false,
    }),
  login: (input: { email: string; password: string }) =>
    request("/api/auth/login", {
      schema: tokenResponseSchema,
      method: "POST",
      body: input,
      auth: false,
    }),
  logout: (refreshToken: string) =>
    request("/api/auth/logout", {
      schema: z.null(),
      method: "POST",
      body: { refresh_token: refreshToken },
      auth: false,
    }),
  me: () => request("/api/auth/me", { schema: userSchema }),

  products: (filters: ProductFilters, signal?: AbortSignal) =>
    request("/api/catalog/products", { schema: productPageSchema, query: { ...filters }, signal }),
  productBySlug: (slug: string) =>
    request(`/api/catalog/products/slug/${encodeURIComponent(slug)}`, { schema: productSchema }),
  productsByIds: (ids: string[]) =>
    request("/api/catalog/products/by-ids", {
      schema: productPageSchema,
      query: { ids: ids.join(",") },
    }).then((page) => page.items),
  categories: () => request("/api/catalog/categories", { schema: z.array(categorySchema) }),
  merchantProducts: async (merchantId: string, signal?: AbortSignal) => {
    const found: Product[] = [];
    for (let page = 1; page <= MAX_PAGES; page++) {
      const res = await request("/api/catalog/products", {
        schema: productPageSchema,
        query: { page, page_size: 48, sort: "newest" },
        signal,
      });
      found.push(...res.items.filter((p) => p.merchant.id === merchantId));
      if (page * res.page_size >= res.total) break;
    }
    return found;
  },
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

  stock: (productIds: string[]) =>
    request("/api/inventory/stock", {
      schema: z.array(stockSchema),
      query: { product_ids: productIds.join(",") },
    }),

  myStock: () => request("/api/inventory/stock/mine", { schema: z.array(stockSchema) }),
  setStock: (productId: string, available: number) =>
    request(`/api/inventory/stock/${productId}`, {
      schema: stockSchema,
      method: "PUT",
      body: { available },
    }),

  createOrder: (input: CreateOrderInput, idempotencyKey: string) =>
    request("/api/orders", {
      schema: createOrderResponseSchema,
      method: "POST",
      body: input,
      headers: { "Idempotency-Key": idempotencyKey },
    }),
  order: (id: string) => request(`/api/orders/${id}`, { schema: orderSchema }),
  orders: (customerId: string, page = 1, pageSize = 10) =>
    request("/api/orders", {
      schema: orderPageSchema,
      query: { customer_id: customerId, page, page_size: pageSize },
    }),

  paymentByOrder: async (orderId: string): Promise<Payment | PaymentPending> => {
    const res = await authedFetch(buildUrl(`/api/payments/by-order/${orderId}`), {
      headers: { Accept: "application/json" },
    });
    if (res.status === 202) {
      return { pending: true, retryAfter: parseRetryAfter(res.headers.get("Retry-After")) };
    }
    if (!res.ok) throw await toError(res);
    const parsed = paymentSchema.safeParse(await res.json());
    if (!parsed.success) throw new ApiError("Resposta inesperada do servidor.", res.status);
    return parsed.data;
  },
  devPay: (chargeId: string) =>
    request(`/api/payments/dev/psp/charges/${chargeId}/pay`, {
      schema: z.unknown(),
      method: "POST",
    }),

  merchantSummary: (merchantId: string, days = 30) =>
    request(`/api/ledger/merchants/${merchantId}/summary`, {
      schema: merchantSummarySchema,
      query: { days },
    }),
  merchantEntries: (merchantId: string, page = 1, pageSize = 8) =>
    request(`/api/ledger/accounts/merchant:${merchantId}/entries`, {
      schema: ledgerEntryPageSchema,
      query: { page, page_size: pageSize },
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
  reconciliation: () => request("/api/ledger/reconciliation", { schema: reconciliationSchema }),

  notifications: (customerId: string, page = 1, pageSize = 20) =>
    request("/api/notifications", {
      schema: notificationPageSchema,
      query: { customer_id: customerId, page, page_size: pageSize },
    }),
  notificationPreviewUrl: (id: string) => buildUrl(`/api/notifications/${id}/preview`),
};
