import { beforeEach, describe, expect, it } from "vitest";
import { PRODUCTS } from "@/mocks/data";
import { MAX_PER_ITEM, selectCount, selectSubtotal, useCart } from "./cart";
import { clearIdempotencyKey, getIdempotencyKey, signatureOf } from "./customer";

const [a, b] = PRODUCTS;
if (!a || !b) throw new Error("seed missing");

describe("cart store", () => {
  beforeEach(() => useCart.getState().clear());

  it("adds, merges and totals items", () => {
    useCart.getState().add(a);
    useCart.getState().add(a, 2);
    useCart.getState().add(b);
    const s = useCart.getState();
    expect(s.lines).toHaveLength(2);
    expect(selectCount(s)).toBe(4);
    expect(selectSubtotal(s)).toBe(a.price_cents * 3 + b.price_cents);
  });

  it("caps quantity by stock and by the per item limit", () => {
    useCart.getState().add(a, 4, 3);
    expect(useCart.getState().lines[0]?.quantity).toBe(3);
    useCart.getState().setQuantity(a.id, 99);
    expect(useCart.getState().lines[0]?.quantity).toBe(MAX_PER_ITEM);
  });

  it("removes a line when quantity reaches zero", () => {
    useCart.getState().add(a);
    useCart.getState().setQuantity(a.id, 0);
    expect(useCart.getState().lines).toHaveLength(0);
  });

  it("persists to localStorage", () => {
    useCart.getState().add(a);
    expect(localStorage.getItem("praca-cart")).toContain(a.slug);
  });
});

describe("idempotency key", () => {
  it("is stable for the same attempt and changes when the cart changes", () => {
    clearIdempotencyKey();
    const contact = { name: "Ana Lima", email: "ana@x.com" };
    const s1 = signatureOf([{ product_id: "1", quantity: 1 }], contact);
    const k1 = getIdempotencyKey(s1);
    expect(getIdempotencyKey(s1)).toBe(k1);
    const s2 = signatureOf([{ product_id: "1", quantity: 2 }], contact);
    expect(getIdempotencyKey(s2)).not.toBe(k1);
    clearIdempotencyKey();
  });
});
