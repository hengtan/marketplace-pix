import { z } from "zod";
import { buildUrl, request } from "./client";
import {
  categorySchema,
  createOrderResponseSchema,
  ledgerEntryPageSchema,
  merchantSummarySchema,
  notificationPageSchema,
  orderPageSchema,
  orderSchema,
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

export interface RegisterInput {
  name: string;
  email: string;
  password: string;
}

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

  stock: (productIds: string[]) =>
    request("/api/inventory/stock", {
      schema: z.array(stockSchema),
      query: { product_ids: productIds.join(",") },
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

  paymentByOrder: (orderId: string) =>
    request(`/api/payments/by-order/${orderId}`, { schema: paymentSchema }),
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
  reconciliation: () => request("/api/ledger/reconciliation", { schema: reconciliationSchema }),

  notifications: (customerId: string, page = 1, pageSize = 20) =>
    request("/api/notifications", {
      schema: notificationPageSchema,
      query: { customer_id: customerId, page, page_size: pageSize },
    }),
  notificationPreviewUrl: (id: string) => buildUrl(`/api/notifications/${id}/preview`),
};
