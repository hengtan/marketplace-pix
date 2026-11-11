import { getRouteApi, useNavigate } from "@tanstack/react-router";
import { ArrowDownUp, Search, SearchX, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ProductFilters, ProductSort } from "@/api/endpoints";
import { ErrorState, EmptyState } from "@/components/states";
import { ProductCard, ProductCardSkeleton } from "@/components/product-card";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { Hero } from "@/features/hero";
import { useCategories, useProductsInfinite, useStock } from "@/hooks/queries";
import { useDebounced, usePageTitle } from "@/hooks/utils";
import { cn } from "@/lib/utils";

const route = getRouteApi("/");

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
      navigate({ search: (prev) => ({ ...prev, q: debounced.trim() || undefined }), replace: true });
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
      <Hero />

      <section aria-labelledby="cats-title" className="mx-auto max-w-7xl px-4 sm:px-6">
        <h2 id="cats-title" className="sr-only">
          Categorias
        </h2>
        <ul className="grid gap-3 sm:grid-cols-3">
          {(categories ?? []).map((c, i) => {
            const active = search.categoria === c.slug;
            return (
              <li key={c.slug}>
                <button
                  type="button"
                  aria-pressed={active}
                  onClick={() =>
                    navigate({ search: (prev) => ({ ...prev, categoria: active ? undefined : c.slug }) })
                  }
                  className={cn(
                    "group flex w-full items-end justify-between rounded-lg border p-5 text-left transition-[background-color,border-color,transform] duration-300 hover:-translate-y-0.5",
                    active
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-surface hover:border-primary",
                  )}
                >
                  <span>
                    <span className={cn("block text-sm", active ? "opacity-80" : "text-muted")}>
                      {c.count} produtos
                    </span>
                    <span className="mt-1 block font-display text-2xl font-semibold tracking-tight">{c.label}</span>
                  </span>
                  <span
                    aria-hidden
                    className={cn(
                      "font-display text-5xl font-bold opacity-20 transition-opacity group-hover:opacity-40",
                    )}
                  >
                    {["T", "C", "E"][i]}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="grid-title" className="mx-auto mt-14 max-w-7xl px-4 sm:px-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 id="grid-title" className="text-3xl font-semibold sm:text-4xl">
              {search.q ? `Resultados para "${search.q}"` : "Vitrine"}
            </h2>
            <p className="mt-1 text-muted" aria-live="polite">
              {query.isPending ? "Carregando produtos..." : `${total} ${total === 1 ? "produto" : "produtos"}`}
            </p>
          </div>
        </div>

        <div className="mt-6 grid gap-3 md:grid-cols-[1fr_auto_auto]">
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
              className="pl-11"
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
                  search: (prev) => ({ ...prev, preco: e.target.value === "todos" ? undefined : e.target.value }),
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
                    ordem: e.target.value === "relevance" ? undefined : (e.target.value as ProductSort),
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

        {hasFilters && (
          <div className="mt-3">
            <Button variant="ghost" size="sm" onClick={clear}>
              <X /> Limpar filtros
            </Button>
          </div>
        )}

        <div className="mt-8">
          {query.isError ? (
            <ErrorState
              message={query.error instanceof Error ? query.error.message : undefined}
              onRetry={() => query.refetch()}
              title="Não foi possível carregar os produtos"
            />
          ) : query.isPending ? (
            <ul className="grid grid-cols-2 gap-x-4 gap-y-10 md:grid-cols-3 lg:grid-cols-4" aria-busy>
              {Array.from({ length: 8 }, (_, i) => (
                <li key={i}>
                  <ProductCardSkeleton />
                </li>
              ))}
            </ul>
          ) : products.length === 0 ? (
            <EmptyState
              icon={<SearchX className="size-7" />}
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
                "grid grid-cols-2 gap-x-4 gap-y-10 transition-opacity md:grid-cols-3 lg:grid-cols-4",
                query.isPlaceholderData && "opacity-60",
              )}
            >
              {products.map((p, i) => (
                <li key={p.id}>
                  <ProductCard product={p} available={stock?.[p.id]} priority={i < 4} />
                </li>
              ))}
            </ul>
          )}
          <div ref={sentinel} className="h-px" />
          {query.hasNextPage && (
            <div className="mt-10 flex justify-center">
              <Button variant="outline" size="lg" onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>
                {query.isFetchingNextPage ? "Carregando..." : "Ver mais produtos"}
              </Button>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
