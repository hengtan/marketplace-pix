import { describe, expect, it } from "vitest";
import { contactSchema } from "@/features/checkout-schema";
import { buildCategories, PRODUCTS } from "@/mocks/data";
import { categorySchema, orderSchema, paymentSchema, productSchema } from "./schemas";

describe("schemas", () => {
  it("accepts every seeded product", () => {
    expect(PRODUCTS).toHaveLength(24);
    for (const p of PRODUCTS) expect(productSchema.safeParse(p).success).toBe(true);
    expect(PRODUCTS.filter((p) => p.image_url === null).length).toBeGreaterThan(0);
  });

  it("accepts categories", () => {
    for (const c of buildCategories()) expect(categorySchema.safeParse(c).success).toBe(true);
  });

  it("rejects a product with a bad price", () => {
    expect(productSchema.safeParse({ ...PRODUCTS[0], price_cents: "10" }).success).toBe(false);
  });

  it("validates orders and payments", () => {
    const order = {
      id: "o1",
      customer_id: "c1",
      customer_name: "Ana",
      customer_email: "a@b.co",
      status: "PENDING",
      currency: "BRL",
      total_cents: 100,
      created_at: new Date().toISOString(),
      cancel_reason: null,
      items: [{ product_id: "p", merchant_id: "m", quantity: 1, unit_price_cents: 100 }],
    };
    expect(orderSchema.safeParse(order).success).toBe(true);
    expect(orderSchema.safeParse({ ...order, status: "PAGO" }).success).toBe(false);
    expect(
      paymentSchema.safeParse({
        id: "p",
        order_id: "o1",
        status: "PENDING",
        amount_cents: 100,
        currency: "BRL",
        pix_code: "000201",
        psp_charge_id: "ch_1",
        expires_at: new Date().toISOString(),
        confirmed_at: null,
      }).success,
    ).toBe(true);
  });

  it("validates the contact form", () => {
    expect(contactSchema.safeParse({ name: "Ana Lima", email: "ana@exemplo.com" }).success).toBe(
      true,
    );
    expect(contactSchema.safeParse({ name: "Ana", email: "ana@exemplo.com" }).success).toBe(false);
    expect(contactSchema.safeParse({ name: "Ana Lima", email: "ana" }).success).toBe(false);
    expect(contactSchema.safeParse({ name: "Ana Lima", email: "" }).success).toBe(false);
  });
});
