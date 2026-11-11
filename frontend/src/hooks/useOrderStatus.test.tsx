import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { api } from "@/api/endpoints";
import { PRODUCTS } from "@/mocks/data";
import * as db from "@/mocks/db";
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
