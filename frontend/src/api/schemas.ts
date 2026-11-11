import * as z from "zod/mini";

export const paged = <T extends z.ZodMiniType>(item: T) =>
  z.object({
    items: z.array(item),
    total: z.int(),
    page: z.int(),
    page_size: z.int(),
  });

export const merchantRefSchema = z.object({ id: z.string(), slug: z.string(), name: z.string() });

export const productSchema = z.object({
  id: z.string(),
  slug: z.string(),
  name: z.string(),
  description: z.string(),
  price_cents: z.int(),
  currency: z.string(),
  category: z.string(),
  image_url: z.nullable(z.string()),
  rating: z.number(),
  reviews_count: z.int(),
  tags: z.array(z.string()),
  merchant: merchantRefSchema,
  created_at: z.string(),
});
export type Product = z.infer<typeof productSchema>;

export const productPageSchema = paged(productSchema);
export type ProductPage = z.infer<typeof productPageSchema>;

export const categorySchema = z.object({ slug: z.string(), label: z.string(), count: z.number() });
export type Category = z.infer<typeof categorySchema>;

export const stockSchema = z.object({
  product_id: z.string(),
  available: z.int(),
  reserved: z.optional(z.int()),
});
export type Stock = z.infer<typeof stockSchema>;

export const orderStatusSchema = z.enum(["PENDING", "PAID", "CANCELLED"]);
export type OrderStatus = z.infer<typeof orderStatusSchema>;

export const orderItemSchema = z.object({
  product_id: z.string(),
  merchant_id: z.string(),
  quantity: z.int(),
  unit_price_cents: z.int(),
});

export const orderSchema = z.object({
  id: z.string(),
  customer_id: z.string(),
  customer_name: z.string(),
  customer_email: z.string(),
  status: orderStatusSchema,
  currency: z.string(),
  total_cents: z.int(),
  created_at: z.string(),
  cancel_reason: z.nullable(z.string()),
  items: z.array(orderItemSchema),
});
export type Order = z.infer<typeof orderSchema>;
export const orderPageSchema = paged(orderSchema);

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

export const createOrderResponseSchema = z.object({ id: z.string() });

export const paymentStatusSchema = z.enum(["PENDING", "CONFIRMED", "EXPIRED", "CANCELLED"]);
export const paymentSchema = z.object({
  id: z.string(),
  order_id: z.string(),
  status: paymentStatusSchema,
  amount_cents: z.int(),
  currency: z.string(),
  pix_code: z.string(),
  psp_charge_id: z.string(),
  expires_at: z.string(),
  confirmed_at: z.nullable(z.string()),
});
export type Payment = z.infer<typeof paymentSchema>;

export const merchantSummarySchema = z.object({
  merchant_id: z.string(),
  currency: z.string(),
  balance_cents: z.int(),
  gross_sales_cents: z.int(),
  platform_fees_cents: z.int(),
  net_sales_cents: z.int(),
  orders_count: z.int(),
  daily: z.array(
    z.object({
      date: z.string(),
      gross_cents: z.int(),
      net_cents: z.int(),
      orders: z.int(),
    }),
  ),
});
export type MerchantSummary = z.infer<typeof merchantSummarySchema>;

export const ledgerEntrySchema = z.object({
  id: z.string(),
  transaction_id: z.string(),
  direction: z.enum(["DEBIT", "CREDIT"]),
  amount_cents: z.int(),
  description: z.string(),
  order_id: z.nullable(z.string()),
  created_at: z.string(),
});
export type LedgerEntry = z.infer<typeof ledgerEntrySchema>;
export const ledgerEntryPageSchema = paged(ledgerEntrySchema);

export const reconciliationSchema = z.object({
  balanced: z.boolean(),
  total_debits_cents: z.int(),
  total_credits_cents: z.int(),
  transactions_count: z.int(),
  checked_at: z.string(),
});
export type Reconciliation = z.infer<typeof reconciliationSchema>;

export const notificationSchema = z.object({
  id: z.string(),
  kind: z.enum(["ORDER_CREATED", "PIX_READY", "ORDER_PAID", "ORDER_CANCELLED"]),
  subject: z.string(),
  status: z.enum(["QUEUED", "SENT", "FAILED"]),
  order_id: z.nullable(z.string()),
  created_at: z.string(),
  sent_at: z.nullable(z.string()),
});
export type Notification = z.infer<typeof notificationSchema>;
export const notificationPageSchema = paged(notificationSchema);

export const errorSchema = z.object({ detail: z.union([z.string(), z.array(z.unknown())]) });

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string(),
  roles: z.array(z.string()),
  merchant_id: z.nullish(z.string()),
});
export type User = z.infer<typeof userSchema>;

export const tokenResponseSchema = z.object({
  access_token: z.string(),
  refresh_token: z.string(),
  token_type: z.string(),
  expires_in: z.number(),
  user: userSchema,
});
export type TokenResponse = z.infer<typeof tokenResponseSchema>;

export const refreshResponseSchema = z.object({
  access_token: z.string(),
  refresh_token: z.optional(z.string()),
  token_type: z.string(),
  expires_in: z.number(),
});
