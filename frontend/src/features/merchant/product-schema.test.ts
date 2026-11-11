import { describe, expect, it } from "vitest";
import type { Product } from "@/api/schemas";
import {
  formDefaults,
  parseTags,
  productFormSchema,
  toNewProduct,
  toPatch,
} from "./product-schema";

const product: Product = {
  id: "p1",
  slug: "mochila",
  name: "Mochila de Trilha 30L",
  description: "Mochila resistente para trilhas longas.",
  price_cents: 31990,
  currency: "BRL",
  category: "esporte",
  image_url: null,
  rating: 4.5,
  reviews_count: 10,
  tags: ["trilha", "mochila"],
  merchant: { id: "m", slug: "trilha-sports", name: "Trilha Sports" },
  created_at: "2026-11-01T00:00:00Z",
};

const valid = {
  name: "  Corda de Pular  ",
  description: "Corda leve com rolamento duplo.",
  price: "49,90",
  category: "esporte",
  tags: "treino, cardio, treino",
  stock: "12",
};

describe("productFormSchema", () => {
  it("accepts a valid form", () => {
    expect(productFormSchema.safeParse(valid).success).toBe(true);
  });
  it("reports the first problem per field in pt-BR", () => {
    const res = productFormSchema.safeParse({
      ...valid,
      name: "ab",
      price: "0",
      category: "",
      stock: "-1",
    });
    expect(res.success).toBe(false);
    const messages = res.error?.issues.map((i) => i.message) ?? [];
    expect(messages).toContain("Use ao menos 3 caracteres");
    expect(messages).toContain("Informe um preço válido, como 49,90");
    expect(messages).toContain("Escolha uma categoria");
    expect(messages).toContain("Use um número inteiro de 0 a 100.000");
  });
  it("rejects prices above the limit and empty descriptions", () => {
    expect(productFormSchema.safeParse({ ...valid, price: "9.999.999,00" }).success).toBe(false);
    expect(productFormSchema.safeParse({ ...valid, description: "curta" }).success).toBe(false);
  });
  it("treats a blank stock as zero", () => {
    expect(productFormSchema.safeParse({ ...valid, stock: "" }).success).toBe(true);
  });
});

describe("payload builders", () => {
  it("normalizes the create payload", () => {
    expect(toNewProduct(valid, "m1")).toEqual({
      name: "Corda de Pular",
      description: "Corda leve com rolamento duplo.",
      price_cents: 4990,
      category: "esporte",
      tags: ["treino", "cardio"],
      merchant_id: "m1",
    });
    expect(toNewProduct(valid).merchant_id).toBeUndefined();
  });
  it("sends only changed fields on edit", () => {
    const form = { ...formDefaults(product), price: "299,90" };
    expect(toPatch(form, product)).toEqual({ price_cents: 29990 });
    expect(toPatch(formDefaults(product), product)).toEqual({});
    expect(toPatch({ ...formDefaults(product), name: "Mochila Nova" }, product)).toEqual({
      name: "Mochila Nova",
    });
  });
  it("limits and dedupes tags", () => {
    expect(parseTags("a, b,,a , c")).toEqual(["a", "b", "c"]);
    expect(parseTags(Array.from({ length: 20 }, (_, i) => `t${i}`).join(","))).toHaveLength(10);
  });
});
