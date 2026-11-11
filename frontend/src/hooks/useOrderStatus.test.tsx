import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { api } from "@/api/endpoints";
import { stockSchema } from "@/api/schemas";
import { env } from "@/lib/env";
import { PRODUCTS } from "@/mocks/data";
import * as db from "@/mocks/db";
import { server } from "@/mocks/server";
import { wrapper } from "@/test/utils";
import { useOrderStatus } from "./useOrderStatus";

const product = PRODUCTS[0];
if (!product) throw new Error("seed missing");

function place(email = "ana@exemplo.com", quantity = 1) {
  return db.createOrder(
    {
      customer_id: "c1",
      customer_name: "Ana Lima",
      customer_email: email,
      items: [{ product_id: product?.id ?? "", quantity }],
    },
    `key-${Math.random()}`,
  ).id;
}

describe("useOrderStatus", () => {
  beforeEach(() => db.resetDb());

  it("polls while PENDING and flips to PAID after the simulated payment", async () => {
    const id = place();
    const { result } = renderHook(() => useOrderStatus(id, 40), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.order?.status).toBe("PENDING"));
    await waitFor(() => expect(result.current.payment?.status).toBe("PENDING"));
    expect(result.current.isLive).toBe(true);

    const charge = result.current.payment?.psp_charge_id ?? "";
    await api.devPay(charge);
    await waitFor(() => expect(result.current.order?.status).toBe("PAID"));
    await waitFor(() => expect(result.current.payment?.status).toBe("CONFIRMED"));
    expect(result.current.isLive).toBe(false);
  });

  it("treats 202 as a charge still being created and refetches after Retry-After", async () => {
    const id = place();
    let calls = 0;
    const real = db.getPayment(id);
    server.use(
      http.get(`${env.apiUrl.replace(/\/$/, "")}/api/payments/by-order/:orderId`, () => {
        calls++;
        return calls < 3
          ? HttpResponse.json({}, { status: 202, headers: { "Retry-After": "0" } })
          : HttpResponse.json(real);
      }),
    );
    const { result } = renderHook(() => useOrderStatus(id, 40), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.order?.status).toBe("PENDING"));
    expect(result.current.payment).toBeUndefined();
    await waitFor(() => expect(result.current.payment?.status).toBe("PENDING"), { timeout: 4000 });
    expect(calls).toBeGreaterThanOrEqual(3);
    expect(result.current.error).toBeNull();
  });

  it("surfaces a cancellation with reason when stock is insufficient", async () => {
    const id = place("ana@exemplo.com", 9999);
    const { result } = renderHook(() => useOrderStatus(id, 50), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.order?.status).toBe("CANCELLED"), { timeout: 4000 });
    expect(result.current.order?.cancel_reason).toBe("out of stock");
  });

  it("reports an error for unknown orders", async () => {
    const { result } = renderHook(() => useOrderStatus("nope", 40), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.error).not.toBeNull());
  });
});

describe("mock order creation", () => {
  beforeEach(() => db.resetDb());

  it("is idempotent for the same key", () => {
    const input = {
      customer_id: "c1",
      customer_name: "Ana Lima",
      customer_email: "a@b.co",
      items: [{ product_id: product?.id ?? "", quantity: 1 }],
    };
    const first = db.createOrder(input, "same");
    const second = db.createOrder(input, "same");
    expect(second.id).toBe(first.id);
    expect(second.replay).toBe(true);
  });
});

describe("public stock", () => {
  it("accepts rows without reserved", () => {
    expect(stockSchema.safeParse({ product_id: "p", available: 3 }).success).toBe(true);
    expect(stockSchema.safeParse({ product_id: "p", available: 3, reserved: 1 }).success).toBe(
      true,
    );
  });

  it("the mock no longer leaks reserved to the public", async () => {
    const rows = await api.stock([product.id]);
    expect(rows[0]).not.toHaveProperty("reserved");
  });
});
