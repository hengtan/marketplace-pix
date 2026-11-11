import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { Product } from "@/api/schemas";
import { prefetchProduct } from "@/hooks/queries";
import { useAddToCart } from "@/hooks/useAddToCart";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ProductImage } from "./product-image";
import { StockBadge } from "./stock-badge";
import { Stars } from "./ui/misc";

interface Props {
  product: Product;
  available?: number;
  priority?: boolean;
}

export function ProductCard({ product, available, priority }: Props) {
  const client = useQueryClient();
  const addToCart = useAddToCart();
  const [added, setAdded] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const soldOut = available !== undefined && available <= 0;

  const onAdd = () => {
    if (!addToCart(product, 1, available)) return;
    setAdded(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setAdded(false), 1400);
  };

  return (
    <article className="group relative flex flex-col" data-testid="product-card">
      <Link
        to="/produto/$slug"
        params={{ slug: product.slug }}
        onMouseEnter={() => prefetchProduct(client, product.slug)}
        onFocus={() => prefetchProduct(client, product.slug)}
        tabIndex={-1}
        aria-hidden
        className="block rounded-lg outline-offset-4"
      >
        <div className="relative overflow-hidden rounded-lg bg-surface-2 shadow-soft transition-[box-shadow,transform] duration-500 ease-out group-hover:shadow-lift">
          <ProductImage
            src={product.image_url}
            alt=""
            category={product.category}
            seed={product.slug}
            priority={priority}
            className={cn(
              "transition-transform duration-700 ease-out group-hover:scale-[1.04]",
              soldOut && "opacity-60 grayscale",
            )}
            size={480}
          />
          <div className="absolute top-3 left-3">
            <StockBadge available={available} hideInStock />
          </div>
        </div>
      </Link>

      <div className="mt-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs text-muted">{product.merchant.name}</p>
          <h3 className="mt-0.5 font-sans text-[0.95rem] leading-snug font-semibold tracking-normal">
            <Link
              to="/produto/$slug"
              params={{ slug: product.slug }}
              onMouseEnter={() => prefetchProduct(client, product.slug)}
              onFocus={() => prefetchProduct(client, product.slug)}
              className="line-clamp-2 hover:text-primary"
            >
              {product.name}
            </Link>
          </h3>
          <Stars rating={product.rating} count={product.reviews_count} className="mt-1.5" />
          <p className="tabular mt-2 font-display text-xl font-semibold tracking-tight">
            {formatMoney(product.price_cents)}
          </p>
        </div>
        <button
          type="button"
          onClick={onAdd}
          disabled={soldOut}
          aria-label={
            soldOut ? `${product.name} esgotado` : `Adicionar ${product.name} ao carrinho`
          }
          className={cn(
            "mt-5 grid size-11 shrink-0 place-items-center rounded-full border transition-[background-color,color,transform,border-color] duration-300 active:scale-90 disabled:opacity-40",
            added
              ? "border-pix bg-pix text-[oklch(0.2_0.06_165)]"
              : "border-border bg-surface hover:border-primary hover:bg-primary hover:text-primary-foreground",
          )}
        >
          {added ? <Check className="size-5" /> : <Plus className="size-5" />}
        </button>
      </div>
    </article>
  );
}

export function ProductCardSkeleton() {
  return (
    <div aria-hidden>
      <div className="skeleton aspect-square rounded-lg" />
      <div className="skeleton mt-3 h-3 w-1/3 rounded" />
      <div className="skeleton mt-2 h-4 w-4/5 rounded" />
      <div className="skeleton mt-2 h-3 w-1/2 rounded" />
      <div className="skeleton mt-3 h-6 w-1/3 rounded" />
    </div>
  );
}
