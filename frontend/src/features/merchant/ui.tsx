import { ArrowDownRight, ArrowUpRight, ChevronLeft, ChevronRight, Minus } from "lucide-react";
import { m, useReducedMotion } from "motion/react";
import type { ComponentProps, ReactNode } from "react";
import { Skeleton } from "@/components/ui/misc";
import { formatPct } from "@/lib/merchant-metrics";
import { EASE, SPRING } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function Segmented<T extends string | number>({
  label,
  options,
  value,
  onChange,
  id,
  render,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  id: string;
  render: (v: T) => ReactNode;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="glass flex flex-wrap gap-1 rounded-full p-1"
    >
      {options.map((o) => {
        const active = o === value;
        return (
          <button
            key={String(o)}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o)}
            className={cn(
              "relative h-10 rounded-full px-4 text-sm font-medium transition-colors",
              active ? "text-background" : "text-muted hover:text-foreground",
            )}
          >
            {active && (
              <m.span
                layoutId={id}
                className="absolute inset-0 rounded-full bg-foreground"
                transition={SPRING}
              />
            )}
            <span className="relative">{render(o)}</span>
          </button>
        );
      })}
    </div>
  );
}

export function Sparkline({
  values,
  tone,
}: {
  values: number[];
  tone: "primary" | "pix" | "plain";
}) {
  const reduce = useReducedMotion();
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values);
  const w = 120;
  const h = 36;
  const pts: [number, number][] = values.map((v, i) => [
    (i / (values.length - 1)) * w,
    h - 4 - ((v - min) / (max - min || 1)) * (h - 8),
  ]);
  const d = pts
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(" ");
  const stroke =
    tone === "primary" ? "stroke-white" : tone === "pix" ? "stroke-pix" : "stroke-primary";
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      className="mt-3 h-9 w-full"
      aria-hidden
      preserveAspectRatio="none"
    >
      <m.path
        d={d}
        fill="none"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        className={stroke}
        initial={reduce ? false : { pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ duration: 1.4, ease: EASE, delay: 0.3 }}
      />
    </svg>
  );
}

export function Delta({
  value,
  invert = false,
  points = false,
  label,
  onPrimary = false,
}: {
  value: number | null;
  invert?: boolean;
  points?: boolean;
  label: string;
  onPrimary?: boolean;
}) {
  if (value === null) {
    return (
      <span className={cn("text-xs", onPrimary ? "opacity-80" : "text-muted")}>
        Sem período anterior para comparar
      </span>
    );
  }
  const flat = Math.abs(value) < 0.0005;
  const up = value > 0;
  const good = flat ? null : invert ? !up : up;
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight;
  const text = points
    ? `${flat ? "" : value > 0 ? "+" : "-"}${(Math.abs(value) * 100).toFixed(1).replace(".", ",")} p.p.`
    : formatPct(value);
  const phrase = flat
    ? "sem variação"
    : `${up ? "alta" : "queda"} de ${points ? text.replace(/^[+-]/, "") : formatPct(Math.abs(value)).replace(/^[+-]/, "")}`;
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
      <span
        className={cn(
          "tabular inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-semibold",
          onPrimary
            ? "bg-white/20 text-white"
            : good === null
              ? "bg-surface-2 text-muted"
              : good
                ? "bg-pix-soft text-pix-ink"
                : "bg-danger-soft text-danger",
        )}
      >
        <Icon className="size-3.5" aria-hidden />
        <span aria-hidden>{text}</span>
        <span className="sr-only">
          {phrase} {label}
        </span>
      </span>
      <span aria-hidden className={cn("text-xs", onPrimary ? "opacity-80" : "text-muted")}>
        {label}
      </span>
    </span>
  );
}

export function Card({
  className,
  children,
  ...rest
}: { className?: string; children: ReactNode } & ComponentProps<"section">) {
  return (
    <section className={cn("panel hairline-top rounded-3xl p-4 sm:p-6", className)} {...rest}>
      {children}
    </section>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="grid gap-2" aria-busy>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-12 w-full rounded-xl" />
      ))}
    </div>
  );
}

export function Pager({
  page,
  pages,
  onChange,
  label,
  info,
}: {
  page: number;
  pages: number;
  onChange: (p: number) => void;
  label: string;
  info?: string;
}) {
  if (pages <= 1 && !info) return null;
  return (
    <nav aria-label={label} className="mt-4 flex flex-wrap items-center justify-between gap-3">
      <span className="tabular text-sm text-muted">{info}</span>
      {pages > 1 && (
        <span className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => onChange(page - 1)}
            disabled={page <= 1}
            className="grid size-11 place-items-center rounded-full border border-border-strong/70 bg-surface/80 text-foreground transition-colors hover:border-primary hover:text-primary disabled:pointer-events-none disabled:opacity-50"
            aria-label="Página anterior"
          >
            <ChevronLeft className="size-4" aria-hidden />
          </button>
          <span className="tabular text-sm text-muted" aria-live="polite">
            {page} de {pages}
          </span>
          <button
            type="button"
            onClick={() => onChange(page + 1)}
            disabled={page >= pages}
            className="grid size-11 place-items-center rounded-full border border-border-strong/70 bg-surface/80 text-foreground transition-colors hover:border-primary hover:text-primary disabled:pointer-events-none disabled:opacity-50"
            aria-label="Próxima página"
          >
            <ChevronRight className="size-4" aria-hidden />
          </button>
        </span>
      )}
    </nav>
  );
}
