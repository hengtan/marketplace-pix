import { useCallback } from "react";
import { toast } from "sonner";
import type { Product } from "@/api/schemas";
import { flyToCart } from "@/lib/fly";
import { MAX_PER_ITEM, useCart } from "@/store/cart";
import { useUi } from "@/store/ui";

export function useAddToCart() {
  const add = useCart((s) => s.add);
  const setCartOpen = useUi((s) => s.setCartOpen);
  const bumpCart = useUi((s) => s.bumpCart);

  return useCallback(
    (product: Product, quantity = 1, available?: number, source?: Element | null) => {
      const inCart =
        useCart.getState().lines.find((l) => l.productId === product.id)?.quantity ?? 0;
      const cap = Math.min(MAX_PER_ITEM, available ?? MAX_PER_ITEM);
      if (available !== undefined && available <= 0) {
        toast.error("Produto esgotado", { description: product.name });
        return false;
      }
      if (inCart >= cap) {
        toast.message("Você já tem o máximo disponível no carrinho", { description: product.name });
        return false;
      }
      add(product, quantity, cap);
      if (source) flyToCart(source, bumpCart);
      else bumpCart();
      toast.success("Adicionado ao carrinho", {
        description: product.name,
        action: { label: "Ver carrinho", onClick: () => setCartOpen(true) },
      });
      return true;
    },
    [add, setCartOpen, bumpCart],
  );
}
