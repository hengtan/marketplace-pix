import { Loader2, Pencil, Search } from "lucide-react";
import { m } from "motion/react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ProductImage } from "@/components/product-image";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/field";
import { Badge } from "@/components/ui/misc";
import { useUpdateStock } from "@/hooks/merchant";
import {
  normalize,
  parseStockInput,
  plural,
  type StockLevel,
  type StockRow,
} from "@/lib/merchant-metrics";
import { EASE } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useMerchant, useMerchantNav } from "./context";
import { useStockRows } from "./data";
import { Card, Segmented, TableSkeleton } from "./ui";

const LEVEL_META: Record<
  StockLevel,
  { label: string; tone: "danger" | "warn" | "pix"; bar: string }
> = {
  out: { label: "Esgotado", tone: "danger", bar: "bg-danger" },
  critical: { label: "Crítico", tone: "danger", bar: "bg-danger" },
  attention: { label: "Atenção", tone: "warn", bar: "bg-sun" },
  healthy: { label: "Saudável", tone: "pix", bar: "bg-pix" },
};
const LEVEL_ORDER: Record<StockLevel, number> = { out: 0, critical: 1, attention: 2, healthy: 3 };

type Filter = "ALL" | "ALERT" | "ATTENTION";
const FILTER_LABEL: Record<Filter, string> = {
  ALL: "Todos",
  ALERT: "Críticos",
  ATTENTION: "Atenção",
};

function Coverage({ row }: { row: StockRow }) {
  const meta = LEVEL_META[row.level];
  const text =
    row.coverageDays === null
      ? "Sem vendas recentes"
      : row.coverageDays < 1
        ? "Menos de 1 dia"
        : `Cobre ~${Math.floor(row.coverageDays)} ${plural(Math.floor(row.coverageDays), "dia", "dias")}`;
  return (
    <div className="min-w-32">
      <div
        role="meter"
        aria-label="Cobertura de estoque"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(row.fill * 100)}
        aria-valuetext={text}
        className="h-2 overflow-hidden rounded-full bg-surface-3"
      >
        <m.div
          className={cn("h-full origin-left rounded-full", meta.bar)}
          style={{ width: `${Math.max(row.available > 0 ? 4 : 0, row.fill * 100)}%` }}
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.8, ease: EASE }}
        />
      </div>
      <span className="mt-1 block text-xs text-muted">{text}</span>
    </div>
  );
}

function StockEditor({
  row,
  name,
  merchantId,
}: {
  row: StockRow;
  name: string;
  merchantId: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useUpdateStock(merchantId);
  const input = useRef<HTMLInputElement>(null);
  const errorId = useId();
  const skipBlur = useRef(false);

  useEffect(() => {
    if (editing) input.current?.select();
  }, [editing]);

  const start = () => {
    setDraft(String(row.available));
    setError(null);
    setEditing(true);
  };

  const commit = () => {
    const parsed = parseStockInput(draft);
    if (!parsed.ok) {
      setError(parsed.error);
      input.current?.focus();
      return;
    }
    setEditing(false);
    setError(null);
    if (parsed.value !== row.available) {
      mutation.mutate({ productId: row.productId, available: parsed.value });
    }
  };

  if (!editing) {
    return (
      <button
        type="button"
        onClick={start}
        aria-label={`Editar estoque de ${name}, ${row.available} disponíveis`}
        className="group inline-flex h-11 min-w-20 items-center justify-end gap-2 rounded-xl px-3 transition-colors hover:bg-primary-soft"
      >
        {mutation.isPending && <Loader2 className="size-3.5 animate-spin text-muted" aria-hidden />}
        <span className="tabular text-base font-semibold">{row.available}</span>
        <Pencil
          className="size-3.5 text-muted opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
          aria-hidden
        />
      </button>
    );
  }

  return (
    <div className="grid justify-items-end gap-1">
      <div className="flex items-center gap-1.5">
        <Input
          ref={input}
          inputMode="numeric"
          aria-label={`Novo estoque disponível de ${name}`}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              skipBlur.current = true;
              commit();
            } else if (e.key === "Escape") {
              e.stopPropagation();
              skipBlur.current = true;
              setEditing(false);
              setError(null);
            }
          }}
          onBlur={() => {
            if (skipBlur.current) {
              skipBlur.current = false;
              return;
            }
            commit();
          }}
          className="tabular h-11 w-24 text-right"
        />
      </div>
      {error && (
        <p id={errorId} role="alert" className="max-w-48 text-right text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function Stock() {
  const { merchantId } = useMerchant();
  const nav = useMerchantNav();
  const { products, stock, rows, productMap } = useStockRows();
  const bulk = useUpdateStock(merchantId);
  const [filter, setFilter] = useState<Filter>("ALL");
  const [text, setText] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkValue, setBulkValue] = useState("");
  const [bulkError, setBulkError] = useState<string | null>(null);

  const visible = useMemo(() => {
    const q = normalize(text.trim());
    return (rows ?? [])
      .filter((r) => {
        if (filter === "ALERT" && r.level !== "out" && r.level !== "critical") return false;
        if (filter === "ATTENTION" && r.level !== "attention") return false;
        return !q || normalize(productMap.get(r.productId)?.name ?? "").includes(q);
      })
      .sort(
        (a, b) =>
          LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level] ||
          (a.coverageDays ?? 999) - (b.coverageDays ?? 999) ||
          a.available - b.available,
      );
  }, [rows, filter, text, productMap]);

  const counts = useMemo(() => {
    const list = rows ?? [];
    return {
      ALL: list.length,
      ALERT: list.filter((r) => r.level === "out" || r.level === "critical").length,
      ATTENTION: list.filter((r) => r.level === "attention").length,
    };
  }, [rows]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allSelected = visible.length > 0 && visible.every((r) => selected.has(r.productId));

  const applyBulk = (value: number | "add10") => {
    for (const id of selected) {
      const row = rows?.find((r) => r.productId === id);
      if (!row) continue;
      bulk.mutate({ productId: id, available: value === "add10" ? row.available + 10 : value });
    }
    setSelected(new Set());
    setBulkValue("");
    setBulkError(null);
  };

  const isError = products.isError || stock.isError;
  const isPending = products.isPending || (stock.isPending && stock.fetchStatus !== "idle");

  return (
    <Card aria-labelledby="estoque-titulo">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="estoque-titulo" className="font-display text-xl font-semibold">
            Estoque
          </h2>
          <p className="mt-1 text-sm text-muted">
            Clique no número disponível para editar. A cobertura usa as vendas dos últimos 14 dias.
          </p>
        </div>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <div className="relative min-w-0 flex-1 basis-64">
          <Search
            className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted"
            aria-hidden
          />
          <Input
            type="search"
            data-merchant-search
            aria-label="Buscar produto no estoque"
            placeholder="Buscar produto"
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="h-11 pl-10"
          />
        </div>
        <Segmented
          id="stock-filter-pill"
          label="Filtrar estoque"
          options={["ALL", "ALERT", "ATTENTION"] as const}
          value={filter}
          onChange={setFilter}
          render={(f) => (
            <>
              {FILTER_LABEL[f]} <span className="tabular opacity-70">{counts[f]}</span>
            </>
          )}
        />
      </div>

      {selected.size > 0 && (
        <m.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          role="region"
          aria-label="Ação em lote"
          className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl bg-primary-soft p-3"
        >
          <span className="px-1 text-sm font-medium">
            {selected.size} {plural(selected.size, "produto selecionado", "produtos selecionados")}
          </span>
          <Button size="sm" variant="outline" onClick={() => applyBulk("add10")}>
            Somar 10 unidades
          </Button>
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              const parsed = parseStockInput(bulkValue);
              if (!parsed.ok) return setBulkError(parsed.error);
              applyBulk(parsed.value);
            }}
          >
            <Input
              inputMode="numeric"
              aria-label="Definir o mesmo estoque para os selecionados"
              placeholder="Definir para"
              aria-invalid={bulkError ? true : undefined}
              value={bulkValue}
              onChange={(e) => {
                setBulkValue(e.target.value);
                setBulkError(null);
              }}
              className="tabular h-9 w-32 rounded-lg px-3 text-sm"
            />
            <Button size="sm" type="submit">
              Aplicar
            </Button>
          </form>
          {bulkError && (
            <span role="alert" className="text-sm text-danger">
              {bulkError}
            </span>
          )}
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Limpar seleção
          </Button>
        </m.div>
      )}

      <div className="mt-5">
        {isError ? (
          <ErrorState
            error={products.error ?? stock.error}
            onRetry={() => {
              void products.refetch();
              void stock.refetch();
            }}
            title="Não foi possível carregar o estoque"
          />
        ) : isPending ? (
          <TableSkeleton rows={8} />
        ) : (rows ?? []).length === 0 ? (
          <EmptyState
            art="cart"
            title="Nenhum produto no estoque"
            description="Cadastre seu primeiro produto para controlar as unidades disponíveis."
            action={<Button onClick={nav.newProduct}>Novo produto</Button>}
          />
        ) : visible.length === 0 ? (
          <EmptyState
            art="search"
            title="Nada por aqui"
            description={
              filter === "ALL"
                ? "Nenhum produto com esse nome."
                : "Nenhum produto neste nível de alerta."
            }
            action={
              <Button
                variant="outline"
                onClick={() => {
                  setFilter("ALL");
                  setText("");
                }}
              >
                Limpar filtros
              </Button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] text-left text-sm">
              <caption className="sr-only">Estoque dos produtos da loja</caption>
              <thead className="text-xs tracking-wide text-muted uppercase">
                <tr className="border-b border-border">
                  <th scope="col" className="w-10 py-2 pr-2">
                    <input
                      type="checkbox"
                      aria-label="Selecionar todos os produtos listados"
                      checked={allSelected}
                      onChange={() =>
                        setSelected(
                          allSelected ? new Set() : new Set(visible.map((r) => r.productId)),
                        )
                      }
                      className="size-5 accent-[var(--primary)]"
                    />
                  </th>
                  <th scope="col" className="py-2 pr-4 font-medium">
                    Produto
                  </th>
                  <th scope="col" className="py-2 pr-2 text-right font-medium">
                    Disponível
                  </th>
                  <th scope="col" className="hidden py-2 pr-4 text-right font-medium sm:table-cell">
                    Reservado
                  </th>
                  <th scope="col" className="hidden py-2 pr-4 font-medium md:table-cell">
                    Cobertura
                  </th>
                  <th scope="col" className="py-2 font-medium">
                    Situação
                  </th>
                </tr>
              </thead>
              <tbody>
                {visible.map((r, i) => {
                  const p = productMap.get(r.productId);
                  const name = p?.name ?? "Produto";
                  const meta = LEVEL_META[r.level];
                  const critical = r.level === "out" || r.level === "critical";
                  return (
                    <m.tr
                      key={r.productId}
                      layout="position"
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.4, delay: Math.min(i, 10) * 0.03, ease: EASE }}
                      data-testid="stock-row"
                      className={cn(
                        "border-b border-border/60 transition-colors last:border-0 hover:bg-primary-soft/40",
                        critical && "bg-danger-soft/50 shadow-[inset_3px_0_0_var(--danger)]",
                      )}
                    >
                      <td className="py-2 pr-2">
                        <input
                          type="checkbox"
                          aria-label={`Selecionar ${name}`}
                          checked={selected.has(r.productId)}
                          onChange={() => toggle(r.productId)}
                          className="size-5 accent-[var(--primary)]"
                        />
                      </td>
                      <td className="py-2 pr-4">
                        <span className="flex items-center gap-3">
                          {p && (
                            <ProductImage
                              src={p.image_url}
                              alt=""
                              category={p.category}
                              seed={p.slug}
                              size={80}
                              className="size-11 shrink-0 rounded-xl"
                            />
                          )}
                          <span className="min-w-0">
                            <span className="block max-w-[14rem] truncate font-medium">{name}</span>
                            <span className="block text-xs text-muted md:hidden">
                              {r.coverageDays === null
                                ? "Sem vendas recentes"
                                : `~${Math.floor(r.coverageDays)} dias`}
                            </span>
                          </span>
                        </span>
                      </td>
                      <td className="py-2 pr-2 text-right">
                        <StockEditor
                          key={`${r.productId}-${r.available}`}
                          row={r}
                          name={name}
                          merchantId={merchantId}
                        />
                      </td>
                      <td className="tabular hidden py-2 pr-4 text-right text-muted sm:table-cell">
                        {r.reserved}
                      </td>
                      <td className="hidden py-2 pr-4 md:table-cell">
                        <Coverage row={r} />
                      </td>
                      <td className="py-2">
                        <Badge tone={meta.tone}>{meta.label}</Badge>
                      </td>
                    </m.tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Card>
  );
}
