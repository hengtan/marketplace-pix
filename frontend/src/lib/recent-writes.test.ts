import { beforeEach, describe, expect, it } from "vitest";
import type { Product } from "@/api/schemas";
import {
  applyRecentWrites,
  forgetRecentWrites,
  rememberCreated,
  rememberPatched,
  rememberRemoved,
} from "./recent-writes";

function product(id: string, name = id, price = 1000, merchant = "m1"): Product {
  return {
    id,
    slug: id,
    name,
    description: "d",
    price_cents: price,
    currency: "BRL",
    category: "esporte",
    image_url: null,
    rating: 0,
    reviews_count: 0,
    tags: [],
    merchant: { id: merchant, slug: merchant, name: merchant },
    created_at: "2026-11-01T00:00:00Z",
  };
}

describe("recent writes overlay", () => {
  beforeEach(forgetRecentWrites);

  it("hides a deactivated product that a stale list still returns", () => {
    rememberRemoved("b");
    expect(applyRecentWrites([product("a"), product("b")], "m1").map((p) => p.id)).toEqual(["a"]);
  });

  it("keeps the edited values over a stale list", () => {
    rememberPatched(product("a", "Novo nome", 2490));
    const [first] = applyRecentWrites([product("a", "Antigo", 1000)], "m1");
    expect(first).toMatchObject({ name: "Novo nome", price_cents: 2490 });
  });

  it("adds a created product the list does not have yet, only for its own store", () => {
    rememberCreated(product("n", "Novo", 500, "m1"));
    expect(applyRecentWrites([product("a")], "m1").map((p) => p.id)).toEqual(["n", "a"]);
    expect(applyRecentWrites([product("a")], "m2").map((p) => p.id)).toEqual(["a"]);
    expect(applyRecentWrites([product("n"), product("a")], "m1").map((p) => p.id)).toEqual([
      "n",
      "a",
    ]);
  });

  it("forgets writes after the consistency window", () => {
    const t0 = 1_000_000;
    rememberRemoved("b", t0);
    expect(applyRecentWrites([product("b")], "m1", t0 + 200_000).map((p) => p.id)).toEqual(["b"]);
  });

  it("a removal wins over an earlier create or edit", () => {
    rememberCreated(product("n"));
    rememberPatched(product("n", "x"));
    rememberRemoved("n");
    expect(applyRecentWrites([], "m1")).toEqual([]);
  });
});
