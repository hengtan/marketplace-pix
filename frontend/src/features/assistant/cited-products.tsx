import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/api/endpoints";
import type { Product } from "@/api/schemas";
import { ProductImage } from "@/components/product-image";
import { StockBadge } from "@/components/stock-badge";
import { useStock } from "@/hooks/queries";
import { useAddToCart } from "@/hooks/useAddToCart";
import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Citation } from "./types";

function CitedCard({
  n,
  citation,
  product,
  available,
  onNavigate,
}: {
  n: number;
  citation: Citation;
  product: Product | undefined;
  available: number | undefined;
  onNavigate?: () => void;
}) {
  const addToCart = useAddToCart();
  const [added, setAdded] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const soldOut = available !== undefined && available <= 0;

  const onAdd = () => {
    if (!product || !addToCart(product, 1, available)) return;
    setAdded(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setAdded(false), 1400);
  };

  return (
    <li
      data-testid="cited-product"
      className="grid grid-cols-[3.5rem_1fr_auto] items-center gap-3 rounded-lg border border-border bg-surface p-2 pr-3 shadow-soft"
    >
      <div className="relative">
        {product ? (
          <ProductImage
            src={product.image_url}
            alt=""
            category={product.category}
            seed={product.slug}
            size={112}
            className={cn("rounded-md", soldOut && "opacity-60 grayscale")}
          />
        ) : (
          <div className="skeleton aspect-square rounded-md" aria-hidden />
        )}
        <span
          aria-hidden
          className="tabular absolute -top-1 -left-1 grid size-5 place-items-center rounded-full bg-primary text-[0.68rem] leading-none font-semibold text-primary-foreground ring-2 ring-surface"
        >
          {n}
        </span>
      </div>
      <div className="min-w-0">
        <Link
          to="/produto/$slug"
          params={{ slug: citation.slug }}
          onClick={onNavigate}
          className="line-clamp-2 text-sm leading-snug font-semibold hover:text-primary"
        >
          {product?.name ?? citation.name}
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
          {product ? (
            <span className="tabular font-display text-base font-semibold">
              {formatMoney(product.price_cents)}
            </span>
          ) : (
            <span className="skeleton h-4 w-16 rounded" aria-hidden />
          )}
          <StockBadge available={available} hideInStock />
        </div>
      </div>
      <button
        type="button"
        onClick={onAdd}
        disabled={!product || soldOut}
        aria-label={
          soldOut
            ? `${citation.name} esgotado`
            : added
              ? `${citation.name} adicionado ao carrinho`
              : `Adicionar ${citation.name} ao carrinho`
        }
        className={cn(
          "inline-flex h-9 items-center gap-1.5 rounded-full border px-3 text-sm font-medium transition-[background-color,color,border-color,transform] duration-300 active:scale-95 disabled:opacity-40",
          added
            ? "border-pix bg-pix text-[oklch(0.2_0.06_165)]"
            : "border-border bg-surface hover:border-primary hover:bg-primary hover:text-primary-foreground",
        )}
      >
        {added ? <Check className="size-4" aria-hidden /> : <Plus className="size-4" aria-hidden />}
        <span aria-hidden>{added ? "Pronto" : "Adicionar"}</span>
      </button>
    </li>
  );
}

export function CitedProducts({
  citations,
  onNavigate,
}: {
  citations: Citation[];
  onNavigate?: () => void;
}) {
  const entries = citations
    .map((citation, i) => ({ citation, n: i + 1 }))
    .filter(
      (e, i, all) => all.findIndex((o) => o.citation.product_id === e.citation.product_id) === i,
    );
  const ids = entries.map((e) => e.citation.product_id);
  const products = useQuery({
    queryKey: ["assistant-products", [...ids].sort().join(",")],
    queryFn: () => api.productsByIds(ids),
    enabled: ids.length > 0,
    staleTime: 60_000,
    select: (items) => Object.fromEntries(items.map((p) => [p.id, p])),
  });
  const stock = useStock(ids);

  if (entries.length === 0) return null;
  return (
    <section aria-label="Produtos citados" className="mt-4">
      <ul className="grid gap-2">
        {entries.map(({ citation, n }) => (
          <CitedCard
            key={citation.product_id}
            n={n}
            citation={citation}
            product={products.data?.[citation.product_id]}
            available={stock.data?.[citation.product_id]}
            onNavigate={onNavigate}
          />
        ))}
      </ul>
    </section>
  );
}
