import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { merchantApi } from "@/api/merchant";
import { server } from "@/mocks/server";

const MERCHANT = "435c5a06-d955-566e-9daf-776be4040c6f";
const base = "http://localhost:8000";

function product(id: string, merchantId: string) {
  return {
    id,
    slug: `p-${id}`,
    name: `Produto ${id}`,
    description: "d",
    price_cents: 1000,
    currency: "BRL",
    category: "esporte",
    image_url: null,
    rating: 0,
    reviews_count: 0,
    tags: [],
    merchant: { id: merchantId, slug: "m", name: "M" },
    created_at: "2026-11-11T12:00:00Z",
  };
}

describe("merchantApi.merchantProducts", () => {
  it("uses the owner list, which includes deactivated products", async () => {
    server.use(
      http.get(`${base}/api/catalog/products/mine`, () =>
        HttpResponse.json({
          items: [
            { ...product("a", MERCHANT), active: true },
            { ...product("b", MERCHANT), active: false },
          ],
        }),
      ),
    );
    const list = await merchantApi.merchantProducts(MERCHANT);
    expect(list.map((p) => [p.id, p.active])).toEqual([
      ["a", true],
      ["b", false],
    ]);
  });

  it("falls back to the public list, active products only, when the account cannot write", async () => {
    server.use(
      http.get(`${base}/api/catalog/products/mine`, () =>
        HttpResponse.json({ detail: "forbidden" }, { status: 403 }),
      ),
      http.get(`${base}/api/catalog/products`, () =>
        HttpResponse.json({
          items: [product("a", MERCHANT), product("z", "outra-loja")],
          total: 2,
          page: 1,
          page_size: 48,
        }),
      ),
    );
    const list = await merchantApi.merchantProducts(MERCHANT);
    expect(list.map((p) => [p.id, p.active])).toEqual([["a", true]]);
  });

  it("does not hide other failures behind the fallback", async () => {
    server.use(
      http.get(`${base}/api/catalog/products/mine`, () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    await expect(merchantApi.merchantProducts(MERCHANT)).rejects.toThrow();
  });
});
