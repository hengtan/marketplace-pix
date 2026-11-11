import * as z from "zod/mini";
import type { NewProductInput, ProductPatch } from "@/api/merchant";
import type { Product } from "@/api/schemas";
import { centsToInput, parseReais, parseStockInput } from "@/lib/merchant-metrics";

export const MAX_PRICE_CENTS = 100_000_000;

export const productFormSchema = z.object({
  name: z
    .string()
    .check(
      z.trim(),
      z.minLength(3, "Use ao menos 3 caracteres"),
      z.maxLength(120, "Use até 120 caracteres"),
    ),
  description: z
    .string()
    .check(
      z.trim(),
      z.minLength(10, "Descreva com ao menos 10 caracteres"),
      z.maxLength(1000, "Use até 1.000 caracteres"),
    ),
  price: z.string().check(
    z.refine((v) => {
      const cents = parseReais(v);
      return cents !== null && cents > 0 && cents <= MAX_PRICE_CENTS;
    }, "Informe um preço válido, como 49,90"),
  ),
  category: z.string().check(z.minLength(1, "Escolha uma categoria")),
  tags: z.string().check(z.maxLength(200, "Use até 200 caracteres")),
  stock: z
    .string()
    .check(
      z.refine(
        (v) => parseStockInput(v.trim() === "" ? "0" : v).ok,
        "Use um número inteiro de 0 a 100.000",
      ),
    ),
});
export type ProductForm = z.infer<typeof productFormSchema>;

export function parseTags(raw: string): string[] {
  const seen = new Set<string>();
  for (const part of raw.split(",")) {
    const tag = part.trim();
    if (tag) seen.add(tag);
  }
  return [...seen].slice(0, 10);
}

export function formDefaults(product?: Product): ProductForm {
  return {
    name: product?.name ?? "",
    description: product?.description ?? "",
    price: product ? centsToInput(product.price_cents) : "",
    category: product?.category ?? "",
    tags: product?.tags.join(", ") ?? "",
    stock: "0",
  };
}

export function toNewProduct(form: ProductForm, merchantId?: string): NewProductInput {
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    price_cents: parseReais(form.price) ?? 0,
    category: form.category,
    tags: parseTags(form.tags),
    ...(merchantId ? { merchant_id: merchantId } : {}),
  };
}

export function toPatch(form: ProductForm, product: Product): ProductPatch {
  const next = toNewProduct(form);
  const patch: ProductPatch = {};
  if (next.name !== product.name) patch.name = next.name;
  if (next.description !== product.description) patch.description = next.description;
  if (next.price_cents !== product.price_cents) patch.price_cents = next.price_cents;
  if (next.category !== product.category) patch.category = next.category;
  if ((next.tags ?? []).join("|") !== product.tags.join("|")) patch.tags = next.tags;
  return patch;
}
