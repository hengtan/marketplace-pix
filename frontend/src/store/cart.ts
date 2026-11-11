import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Product } from "@/api/schemas";

export const MAX_PER_ITEM = 10;

export interface CartLine {
  productId: string;
  slug: string;
  name: string;
  priceCents: number;
  imageUrl: string | null;
  category: string;
  merchantName: string;
  quantity: number;
}

interface CartState {
  lines: CartLine[];
  add: (product: Product, quantity?: number, max?: number) => void;
  setQuantity: (productId: string, quantity: number) => void;
  remove: (productId: string) => void;
  clear: () => void;
}

export function lineFromProduct(product: Product, quantity: number): CartLine {
  return {
    productId: product.id,
    slug: product.slug,
    name: product.name,
    priceCents: product.price_cents,
    imageUrl: product.image_url,
    category: product.category,
    merchantName: product.merchant.name,
    quantity,
  };
}

export const useCart = create<CartState>()(
  persist(
    (set) => ({
      lines: [],
      add: (product, quantity = 1, max = MAX_PER_ITEM) =>
        set((s) => {
          const cap = Math.min(max, MAX_PER_ITEM);
          const existing = s.lines.find((l) => l.productId === product.id);
          if (existing) {
            return {
              lines: s.lines.map((l) =>
                l.productId === product.id
                  ? { ...l, quantity: Math.min(cap, l.quantity + quantity) }
                  : l,
              ),
            };
          }
          return { lines: [...s.lines, lineFromProduct(product, Math.min(cap, quantity))] };
        }),
      setQuantity: (productId, quantity) =>
        set((s) => ({
          lines:
            quantity <= 0
              ? s.lines.filter((l) => l.productId !== productId)
              : s.lines.map((l) =>
                  l.productId === productId
                    ? { ...l, quantity: Math.min(MAX_PER_ITEM, quantity) }
                    : l,
                ),
        })),
      remove: (productId) =>
        set((s) => ({ lines: s.lines.filter((l) => l.productId !== productId) })),
      clear: () => set({ lines: [] }),
    }),
    { name: "praca-cart", version: 1 },
  ),
);

export const selectCount = (s: CartState) => s.lines.reduce((n, l) => n + l.quantity, 0);
export const selectSubtotal = (s: CartState) =>
  s.lines.reduce((n, l) => n + l.priceCents * l.quantity, 0);
