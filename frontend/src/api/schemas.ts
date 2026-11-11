import { z } from "zod";

export const paged = <T extends z.ZodType>(item: T) =>
  z.object({
    items: z.array(item),
    total: z.number().int(),
    page: z.number().int(),
    page_size: z.number().int(),
  });

export const merchantRefSchema = z.object({ id: z.string(), slug: z.string(), name: z.string() });

export const productSchema = z.object({
  id: z.string(),
  slug: z.string(),
  name: z.string(),
  description: z.string(),
  price_cents: z.number().int(),
  currency: z.string(),
  category: z.string(),
  image_url: z.string().nullable(),
  rating: z.number(),
  reviews_count: z.number().int(),
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
  available: z.number().int(),
  reserved: z.number().int(),
});
export type Stock = z.infer<typeof stockSchema>;

export const orderStatusSchema = z.enum(["PENDING", "PAID", "CANCELLED"]);
export type OrderStatus = z.infer<typeof orderStatusSchema>;

export const orderItemSchema = z.object({
  product_id: z.string(),
  merchant_id: z.string(),
  quantity: z.number().int(),
  unit_price_cents: z.number().int(),
});

export const orderSchema = z.object({
  id: z.string(),
  customer_id: z.string(),
  customer_name: z.string(),
  customer_email: z.string(),
  status: orderStatusSchema,
  currency: z.string(),
  total_cents: z.number().int(),
  created_at: z.string(),
  cancel_reason: z.string().nullable(),
  items: z.array(orderItemSchema),
});
export type Order = z.infer<typeof orderSchema>;
export const orderPageSchema = paged(orderSchema);

export const createOrderResponseSchema = z.object({ id: z.string() });

export const paymentStatusSchema = z.enum(["PENDING", "CONFIRMED", "EXPIRED", "CANCELLED"]);
export const paymentSchema = z.object({
  id: z.string(),
  order_id: z.string(),
  status: paymentStatusSchema,
  amount_cents: z.number().int(),
  currency: z.string(),
  pix_code: z.string(),
  psp_charge_id: z.string(),
  expires_at: z.string(),
  confirmed_at: z.string().nullable(),
});
export type Payment = z.infer<typeof paymentSchema>;

export const merchantSummarySchema = z.object({
  merchant_id: z.string(),
  currency: z.string(),
  balance_cents: z.number().int(),
  gross_sales_cents: z.number().int(),
  platform_fees_cents: z.number().int(),
  net_sales_cents: z.number().int(),
  orders_count: z.number().int(),
  daily: z.array(
    z.object({
      date: z.string(),
      gross_cents: z.number().int(),
      net_cents: z.number().int(),
      orders: z.number().int(),
    }),
  ),
});
export type MerchantSummary = z.infer<typeof merchantSummarySchema>;

export const ledgerEntrySchema = z.object({
  id: z.string(),
  transaction_id: z.string(),
  direction: z.enum(["DEBIT", "CREDIT"]),
  amount_cents: z.number().int(),
  description: z.string(),
  order_id: z.string().nullable(),
  created_at: z.string(),
});
export type LedgerEntry = z.infer<typeof ledgerEntrySchema>;
export const ledgerEntryPageSchema = paged(ledgerEntrySchema);

export const reconciliationSchema = z.object({
  balanced: z.boolean(),
  total_debits_cents: z.number().int(),
  total_credits_cents: z.number().int(),
  transactions_count: z.number().int(),
  checked_at: z.string(),
});
export type Reconciliation = z.infer<typeof reconciliationSchema>;

export const notificationSchema = z.object({
  id: z.string(),
  kind: z.enum(["ORDER_CREATED", "PIX_READY", "ORDER_PAID", "ORDER_CANCELLED"]),
  subject: z.string(),
  status: z.enum(["QUEUED", "SENT", "FAILED"]),
  order_id: z.string().nullable(),
  created_at: z.string(),
  sent_at: z.string().nullable(),
});
export type Notification = z.infer<typeof notificationSchema>;
export const notificationPageSchema = paged(notificationSchema);

export const errorSchema = z.object({ detail: z.union([z.string(), z.array(z.unknown())]) });
