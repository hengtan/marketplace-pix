import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, Plus } from "lucide-react";
import { m } from "motion/react";
import { useEffect, useRef, useState } from "react";
import type { Product } from "@/api/schemas";
import { prefetchProduct } from "@/hooks/queries";
import { useAddToCart } from "@/hooks/useAddToCart";
import { formatMoney } from "@/lib/format";
import { SPRING_POP } from "@/lib/motion";
import { claimTransition } from "@/lib/transition";
import { cn } from "@/lib/utils";
import { useUi } from "@/store/ui";
import { TiltCard } from "./motion/tilt-card";
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
  const imageRef = useRef<HTMLDivElement>(null);
  const lastSlug = useUi((s) => s.lastSlug);
  useEffect(() => () => clearTimeout(timer.current), []);
  const soldOut = available !== undefined && available <= 0;

  const onAdd = () => {
    if (!addToCart(product, 1, available, imageRef.current)) return;
    setAdded(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setAdded(false), 1600);
  };

  const open = () => {
    useUi.getState().setLastSlug(product.slug);
    claimTransition(imageRef.current);
  };

  return (
    <TiltCard className="rounded-[1.6rem]">
      <article
        className="panel group relative flex h-full flex-col rounded-[1.6rem] p-2.5 transition-shadow duration-500 hover:shadow-lift"
        data-testid="product-card"
      >
        <Link
          to="/produto/$slug"
          params={{ slug: product.slug }}
          viewTransition
          onMouseEnter={() => prefetchProduct(client, product.slug)}
          onFocus={() => prefetchProduct(client, product.slug)}
          onClick={open}
          tabIndex={-1}
          aria-hidden
          data-cursor="Ver"
          className="block rounded-[1.2rem] outline-offset-4"
        >
          <div
            ref={imageRef}
            data-vt
            style={lastSlug === product.slug ? { viewTransitionName: "product-hero" } : undefined}
            className="relative overflow-hidden rounded-[1.2rem] shadow-soft"
          >
            <ProductImage
              src={product.image_url}
              alt=""
              category={product.category}
              seed={product.slug}
              priority={priority}
              className={cn(
                "transition-transform duration-700 ease-out group-hover:scale-[1.06]",
                soldOut && "opacity-60 grayscale",
              )}
              size={480}
            />
            <div className="absolute top-3 left-3">
              <StockBadge available={available} hideInStock />
            </div>
          </div>
        </Link>

        <div className="mt-3 flex flex-1 items-start justify-between gap-3 px-1.5 pb-1.5">
          <div className="min-w-0">
            <p className="truncate text-xs font-medium text-muted">{product.merchant.name}</p>
            <h3 className="mt-0.5 font-sans text-[0.95rem] leading-snug font-semibold tracking-normal">
              <Link
                to="/produto/$slug"
                params={{ slug: product.slug }}
                viewTransition
                onMouseEnter={() => prefetchProduct(client, product.slug)}
                onFocus={() => prefetchProduct(client, product.slug)}
                onClick={open}
                className="line-clamp-2 transition-colors hover:text-primary"
              >
                {product.name}
              </Link>
            </h3>
            <Stars rating={product.rating} count={product.reviews_count} className="mt-1.5" />
            <p className="tabular mt-2 font-display text-xl font-semibold tracking-tight">
              {formatMoney(product.price_cents)}
            </p>
          </div>
          <m.button
            type="button"
            onClick={onAdd}
            disabled={soldOut}
            whileTap={{ scale: 0.85 }}
            transition={SPRING_POP}
            aria-label={
              soldOut ? `${product.name} esgotado` : `Adicionar ${product.name} ao carrinho`
            }
            className={cn(
              "relative mt-5 grid size-11 shrink-0 place-items-center overflow-hidden rounded-full border transition-[background-color,color,border-color,box-shadow] duration-300 disabled:opacity-40",
              added
                ? "border-pix bg-pix text-[oklch(0.2_0.06_165)] shadow-[0_8px_20px_-6px_oklch(0.7_0.17_165/0.7)]"
                : "border-border-strong/60 bg-surface hover:border-primary hover:bg-primary hover:text-primary-foreground hover:shadow-glow",
            )}
          >
            <m.span
              key={added ? "ok" : "add"}
              initial={{ scale: 0.3, rotate: -90, opacity: 0 }}
              animate={{ scale: 1, rotate: 0, opacity: 1 }}
              transition={SPRING_POP}
              className="grid place-items-center"
            >
              {added ? <Check className="size-5" strokeWidth={3} /> : <Plus className="size-5" />}
            </m.span>
          </m.button>
        </div>
      </article>
    </TiltCard>
  );
}

export function ProductCardSkeleton() {
  return (
    <div aria-hidden className="panel rounded-[1.6rem] p-2.5">
      <div className="skeleton aspect-square rounded-[1.2rem]" />
      <div className="px-1.5 pb-1.5">
        <div className="skeleton mt-3 h-3 w-1/3 rounded" />
        <div className="skeleton mt-2 h-4 w-4/5 rounded" />
        <div className="skeleton mt-2 h-3 w-1/2 rounded" />
        <div className="skeleton mt-3 h-6 w-1/3 rounded" />
      </div>
    </div>
  );
}
