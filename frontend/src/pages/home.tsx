import { getRouteApi, useNavigate } from "@tanstack/react-router";
import { ArrowDownUp, ArrowRight, Search, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ProductFilters, ProductSort } from "@/api/endpoints";
import { Marquee } from "@/components/motion/marquee";
import { Reveal } from "@/components/motion/reveal";
import { TiltCard } from "@/components/motion/tilt-card";
import { ProductCard, ProductCardSkeleton } from "@/components/product-card";
import { ProductImage } from "@/components/product-image";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { Hero } from "@/features/hero";
import { useCategories, useProductsInfinite, useStock } from "@/hooks/queries";
import { useDebounced, usePageTitle } from "@/hooks/utils";
import { SPRING } from "@/lib/motion";
import { cn } from "@/lib/utils";

const route = getRouteApi("/");

const CATEGORY_ART: Record<string, string> = {
  tecnologia: "fone-bluetooth-nova",
  casa: "luminaria-arco-dourado",
  esporte: "tenis-corrida-vento",
};

const TICKER = [
  "Tecnologia",
  "PIX na hora",
  "Casa e decoração",
  "Estoque em tempo real",
  "Esporte e aventura",
  "Lojistas independentes",
];

function Star() {
  return (
    <svg viewBox="0 0 24 24" className="size-7 shrink-0 fill-primary" aria-hidden>
      <path d="M12 0c.6 6.6 4.8 10.8 12 12-7.2 1.2-11.4 5.4-12 12-.6-6.6-4.8-10.8-12-12C7.2 10.8 11.4 6.6 12 0z" />
    </svg>
  );
}

export const PRICE_RANGES = [
  { id: "todos", label: "Qualquer preço", min: undefined, max: undefined },
  { id: "ate-100", label: "Até R$ 100", min: undefined, max: 10000 },
  { id: "100-300", label: "R$ 100 a R$ 300", min: 10000, max: 30000 },
  { id: "300-mais", label: "Acima de R$ 300", min: 30000, max: undefined },
] as const;

const SORTS: { value: ProductSort; label: string }[] = [
  { value: "relevance", label: "Mais relevantes" },
  { value: "rating", label: "Melhor avaliados" },
  { value: "price_asc", label: "Menor preço" },
  { value: "price_desc", label: "Maior preço" },
  { value: "newest", label: "Mais recentes" },
];

export default function HomePage() {
  usePageTitle("Loja");
  const search = route.useSearch();
  const navigate = useNavigate({ from: "/" });
  const { data: categories } = useCategories();
  const [text, setText] = useState(search.q ?? "");
  const debounced = useDebounced(text, 300);

  useEffect(() => {
    setText(search.q ?? "");
  }, [search.q]);

  useEffect(() => {
    if ((search.q ?? "") !== debounced.trim()) {
      navigate({
        search: (prev) => ({ ...prev, q: debounced.trim() || undefined }),
        replace: true,
      });
    }
  }, [debounced, navigate, search.q]);

  const range = PRICE_RANGES.find((r) => r.id === search.preco) ?? PRICE_RANGES[0];
  const filters: Omit<ProductFilters, "page"> = useMemo(
    () => ({
      q: search.q,
      category: search.categoria,
      min_price_cents: range.min,
      max_price_cents: range.max,
      sort: search.ordem ?? "relevance",
      page_size: 12,
    }),
    [search.q, search.categoria, search.ordem, range.min, range.max],
  );

  const query = useProductsInfinite(filters);
  const products = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data]);
  const total = query.data?.pages[0]?.total ?? 0;
  const { data: stock } = useStock(products.map((p) => p.id));

  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasNextPage) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !isFetchingNextPage) fetchNextPage();
      },
      { rootMargin: "400px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const hasFilters = Boolean(search.q || search.categoria || search.preco || search.ordem);
  const clear = () => {
    setText("");
    navigate({ search: {} });
  };

  return (
    <>
      <Hero productCount={24} merchantCount={3} />

      <Marquee
        label="Destaques da loja"
        className="border-y border-border bg-surface/50 py-5"
        items={TICKER.flatMap((t, i) => [
          <span
            key={t}
            className={cn(
              "font-display text-3xl font-semibold tracking-tight whitespace-nowrap sm:text-4xl",
              i % 2 === 1 && "serif text-primary",
            )}
          >
            {t}
          </span>,
          <Star key={`${t}-s`} />,
        ])}
      />

      <section aria-labelledby="cats-title" className="mx-auto mt-16 max-w-7xl px-4 sm:px-6">
        <h2 id="cats-title" className="sr-only">
          Categorias
        </h2>
        <ul className="grid gap-4 md:grid-cols-3">
          {(categories ?? []).map((c, i) => {
            const active = search.categoria === c.slug;
            return (
              <Reveal as="li" key={c.slug} delay={i * 0.09}>
                <TiltCard className="rounded-[1.75rem]" max={4}>
                  <button
                    type="button"
                    aria-pressed={active}
                    onClick={() =>
                      navigate({
                        search: (prev) => ({ ...prev, categoria: active ? undefined : c.slug }),
                      })
                    }
                    className={cn(
                      "panel group relative flex h-full min-h-44 w-full items-end justify-between overflow-hidden rounded-[1.75rem] p-6 text-left transition-colors duration-300",
                      active && "!border-transparent",
                    )}
                  >
                    {active && (
                      <motion.span
                        layoutId="cat-ring"
                        className="pointer-events-none absolute inset-0 rounded-[1.75rem] border-2 border-primary bg-primary-soft/60"
                        transition={SPRING}
                      />
                    )}
                    <span className="relative z-10">
                      <span className="text-sm font-medium text-muted">{c.count} produtos</span>
                      <span className="mt-1 block font-display text-[1.9rem] leading-none font-semibold tracking-tight">
                        {c.label}
                      </span>
                      <span className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-primary">
                        {active ? "Mostrando agora" : "Ver categoria"}
                        <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-1" />
                      </span>
                    </span>
                    <span className="absolute -top-4 -right-6 w-40 rotate-6 transition-transform duration-700 ease-out group-hover:-translate-y-1 group-hover:rotate-12 group-hover:scale-110">
                      <ProductImage
                        src={null}
                        alt=""
                        category={c.slug}
                        seed={CATEGORY_ART[c.slug] ?? c.slug}
                        className="rounded-[1.6rem] shadow-lift"
                      />
                    </span>
                  </button>
                </TiltCard>
              </Reveal>
            );
          })}
        </ul>
      </section>

      <section
        id="vitrine"
        aria-labelledby="grid-title"
        className="mx-auto mt-20 max-w-7xl px-4 sm:px-6"
      >
        <Reveal className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="grid-title" className="text-title">
              {search.q ? (
                `Resultados para "${search.q}"`
              ) : (
                <>
                  Vitrine <span className="serif text-primary">completa</span>
                </>
              )}
            </h2>
            <p className="mt-2 text-muted" aria-live="polite">
              {query.isPending
                ? "Carregando produtos..."
                : `${total} ${total === 1 ? "produto" : "produtos"}`}
            </p>
          </div>
        </Reveal>

        <div className="glass mt-6 grid gap-3 rounded-[1.4rem] p-2.5 shadow-soft md:grid-cols-[1fr_auto_auto]">
          <div className="relative">
            <label htmlFor="busca" className="sr-only">
              Buscar produtos
            </label>
            <Search className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted" />
            <Input
              id="busca"
              type="search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Buscar fones, mochilas, vasos..."
              className="border-transparent bg-surface/70 pl-11"
              autoComplete="off"
            />
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="preco" className="sr-only">
              Faixa de preço
            </label>
            <Select
              id="preco"
              className="h-12 w-full"
              value={range.id}
              onChange={(e) =>
                navigate({
                  search: (prev) => ({
                    ...prev,
                    preco: e.target.value === "todos" ? undefined : e.target.value,
                  }),
                })
              }
            >
              {PRICE_RANGES.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <ArrowDownUp className="size-4 text-muted" aria-hidden />
            <label htmlFor="ordem" className="sr-only">
              Ordenar por
            </label>
            <Select
              id="ordem"
              className="h-12 w-full"
              value={search.ordem ?? "relevance"}
              onChange={(e) =>
                navigate({
                  search: (prev) => ({
                    ...prev,
                    ordem:
                      e.target.value === "relevance" ? undefined : (e.target.value as ProductSort),
                  }),
                })
              }
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <AnimatePresence>
          {hasFilters && (
            <motion.div
              className="mt-3"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
            >
              <Button variant="ghost" size="sm" onClick={clear}>
                <X /> Limpar filtros
              </Button>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="mt-8">
          {query.isError ? (
            <ErrorState
              message={query.error instanceof Error ? query.error.message : undefined}
              onRetry={() => query.refetch()}
              title="Não foi possível carregar os produtos"
            />
          ) : query.isPending ? (
            <ul className="grid grid-cols-2 gap-3 sm:gap-5 md:grid-cols-3 lg:grid-cols-4" aria-busy>
              {Array.from({ length: 8 }, (_, i) => (
                <li key={i}>
                  <ProductCardSkeleton />
                </li>
              ))}
            </ul>
          ) : products.length === 0 ? (
            <EmptyState
              art="search"
              title="Nenhum produto encontrado"
              description="Tente outra palavra, outra faixa de preço ou remova os filtros."
              action={
                <Button variant="outline" onClick={clear}>
                  Limpar filtros
                </Button>
              }
            />
          ) : (
            <ul
              className={cn(
                "grid grid-cols-2 gap-3 transition-opacity sm:gap-5 md:grid-cols-3 lg:grid-cols-4",
                query.isPlaceholderData && "opacity-60",
              )}
            >
              {products.map((p, i) => (
                <Reveal as="li" key={p.id} delay={(i % 4) * 0.07} y={28}>
                  <ProductCard product={p} available={stock?.[p.id]} priority={i < 4} />
                </Reveal>
              ))}
            </ul>
          )}
          <div ref={sentinel} className="h-px" />
          {query.hasNextPage && (
            <div className="mt-10 flex justify-center">
              <Button
                variant="outline"
                size="lg"
                onClick={() => query.fetchNextPage()}
                disabled={query.isFetchingNextPage}
              >
                {query.isFetchingNextPage ? "Carregando..." : "Ver mais produtos"}
              </Button>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
