import { getRouteApi, Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, QrCode, ShieldCheck, ShoppingBag, Store } from "lucide-react";
import { motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import { AnimatedNumber } from "@/components/motion/animated-number";
import { Magnetic } from "@/components/motion/magnetic";
import { Reveal } from "@/components/motion/reveal";
import { ProductCard } from "@/components/product-card";
import { ProductImage } from "@/components/product-image";
import { QuantityStepper } from "@/components/quantity-stepper";
import { ErrorState } from "@/components/states";
import { StockBadge } from "@/components/stock-badge";
import { Button } from "@/components/ui/button";
import { Badge, Skeleton, Stars } from "@/components/ui/misc";
import { useProduct, useRelatedProducts, useStock } from "@/hooks/queries";
import { useAddToCart } from "@/hooks/useAddToCart";
import { usePageTitle } from "@/hooks/utils";
import { formatMoney as money } from "@/lib/format";
import { MAX_PER_ITEM } from "@/store/cart";
import { useUi } from "@/store/ui";

const route = getRouteApi("/produto/$slug");

function ProductSkeleton() {
  return (
    <div className="mx-auto grid max-w-7xl gap-10 px-4 py-10 sm:px-6 lg:grid-cols-2" aria-busy>
      <Skeleton
        className="aspect-square rounded-[2rem]"
        style={{ viewTransitionName: "product-hero" }}
      />
      <div className="grid content-start gap-4">
        <Skeleton className="h-4 w-1/4" />
        <Skeleton className="h-12 w-4/5" />
        <Skeleton className="h-5 w-1/3" />
        <Skeleton className="h-12 w-1/3" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    </div>
  );
}

export default function ProductPage() {
  const { slug } = route.useParams();
  const navigate = useNavigate();
  const { data: product, isPending, error, refetch } = useProduct(slug);
  usePageTitle(product?.name ?? "Produto");
  const { data: stock } = useStock(product ? [product.id] : []);
  const related = useRelatedProducts(product?.category, product?.id);
  const relatedStock = useStock((related.data ?? []).map((p) => p.id));
  const addToCart = useAddToCart();
  const [qty, setQty] = useState(1);
  const reduce = useReducedMotion();
  const heroRef = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: heroRef, offset: ["start 0.3", "end start"] });
  const heroScale = useTransform(scrollYProgress, [0, 1], [1, 0.92]);
  const heroY = useTransform(scrollYProgress, [0, 1], [0, 30]);
  const setLastSlug = useUi((s) => s.setLastSlug);
  useEffect(() => {
    setLastSlug(slug);
  }, [slug, setLastSlug]);

  if (isPending) return <ProductSkeleton />;
  if (error || !product) {
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
        <ErrorState
          title={missing ? "Produto não encontrado" : "Não foi possível carregar o produto"}
          message={
            missing ? "Esse produto não existe mais ou o link está incorreto." : error?.message
          }
          onRetry={missing ? undefined : () => refetch()}
        />
        <div className="flex justify-center">
          <Button asChild variant="outline">
            <Link to="/">Voltar para a loja</Link>
          </Button>
        </div>
      </div>
    );
  }

  const available = stock?.[product.id];
  const soldOut = available !== undefined && available <= 0;
  const max = Math.min(MAX_PER_ITEM, available ?? MAX_PER_ITEM);
  const quantity = Math.min(qty, Math.max(1, max));

  return (
    <article className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-10">
      <Link
        to="/"
        className="inline-flex items-center gap-2 rounded-md py-2 text-sm text-muted hover:text-foreground"
      >
        <ArrowLeft className="size-4" /> Voltar para a loja
      </Link>

      <div className="mt-4 grid gap-10 lg:grid-cols-[1.1fr_1fr] lg:gap-16">
        <div ref={heroRef} className="relative lg:sticky lg:top-24 lg:self-start">
          <motion.div style={reduce ? undefined : { scale: heroScale, y: heroY }}>
            <div
              data-vt
              style={{ viewTransitionName: "product-hero" }}
              className="relative overflow-hidden rounded-[2rem] shadow-lift ring-1 ring-border"
            >
              <ProductImage
                src={product.image_url}
                alt={product.name}
                category={product.category}
                seed={product.slug}
                priority
                float
                size={960}
              />
            </div>
          </motion.div>
          <div className="absolute top-4 left-4">
            <StockBadge available={available} hideInStock />
          </div>
        </div>

        <div className="grid content-start gap-6">
          <div>
            <p className="flex items-center gap-2 text-sm text-muted">
              <Store className="size-4" /> Vendido por{" "}
              <span className="font-medium text-foreground">{product.merchant.name}</span>
            </p>
            <h1 className="text-title mt-3">{product.name}</h1>
            <Stars
              rating={product.rating}
              count={product.reviews_count}
              className="mt-3 text-base"
            />
          </div>

          <div className="flex flex-wrap items-baseline gap-3">
            <p className="font-display text-5xl font-bold tracking-tight">
              <AnimatedNumber
                value={product.price_cents}
                format={(n) => money(Math.round(n))}
                fromZero
                testId="product-price"
              />
            </p>
            <Badge tone="pix">
              <QrCode className="size-3.5" /> PIX, confirmação na hora
            </Badge>
          </div>

          <p className="max-w-[60ch] text-lg leading-relaxed text-muted">{product.description}</p>

          <ul className="flex flex-wrap gap-2" aria-label="Características">
            {product.tags.map((t) => (
              <li key={t}>
                <Badge>{t}</Badge>
              </li>
            ))}
          </ul>

          <div className="panel hairline-top grid gap-4 rounded-3xl p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">Quantidade</p>
                <p className="text-sm text-muted" aria-live="polite">
                  {soldOut
                    ? "Sem unidades disponíveis"
                    : available !== undefined && available <= 5
                      ? `Últimas ${available} unidades, não deixe para depois`
                      : "Pronta entrega"}
                </p>
              </div>
              <QuantityStepper
                label={product.name}
                value={quantity}
                min={1}
                max={max}
                onChange={setQty}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Button
                size="lg"
                variant="outline"
                disabled={soldOut}
                onClick={() =>
                  addToCart(
                    product,
                    quantity,
                    available,
                    heroRef.current?.querySelector("[data-vt]"),
                  )
                }
              >
                <ShoppingBag /> Adicionar ao carrinho
              </Button>
              <Magnetic className="w-full" strength={0.12}>
                <Button
                  size="lg"
                  variant="pix"
                  className="w-full"
                  disabled={soldOut}
                  onClick={() => {
                    if (addToCart(product, quantity, available)) navigate({ to: "/checkout" });
                  }}
                >
                  {soldOut ? "Esgotado" : "Comprar com PIX"}
                </Button>
              </Magnetic>
            </div>
          </div>

          <p className="flex items-start gap-2 text-sm text-muted">
            <ShieldCheck className="mt-0.5 size-4 shrink-0 text-pix-ink" />O estoque é reservado
            assim que o pedido é criado e liberado se o PIX expirar.
          </p>
        </div>
      </div>

      {(related.data?.length ?? 0) > 0 && (
        <section className="mt-24" aria-labelledby="rel-title">
          <h2 id="rel-title" className="text-heading">
            Quem viu este <span className="serif text-primary">também gostou</span>
          </h2>
          <ul className="mt-6 grid grid-cols-2 gap-3 sm:gap-5 md:grid-cols-4">
            {related.data?.map((p, i) => (
              <Reveal as="li" key={p.id} delay={i * 0.08}>
                <ProductCard product={p} available={relatedStock.data?.[p.id]} />
              </Reveal>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
