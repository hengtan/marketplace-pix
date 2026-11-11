import { cva, type VariantProps } from "class-variance-authority";
import { Star } from "lucide-react";
import type { ComponentProps } from "react";
import { formatRating } from "@/lib/format";
import { cn } from "@/lib/utils";

export function Skeleton({ className, ...props }: ComponentProps<"div">) {
  return <div aria-hidden className={cn("skeleton rounded-md", className)} {...props} />;
}

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium leading-none",
  {
    variants: {
      tone: {
        neutral: "bg-surface-2 text-foreground",
        primary: "bg-primary-soft text-primary",
        pix: "bg-pix-soft text-pix-ink",
        warn: "bg-warn-soft text-warn",
        danger: "bg-danger-soft text-danger",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export function Stars({ rating, count, className }: { rating: number; count?: number; className?: string }) {
  const full = Math.round(rating);
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-sm text-muted", className)}
      role="img"
      aria-label={`Nota ${formatRating(rating)} de 5${count !== undefined ? `, ${count} avaliações` : ""}`}
    >
      <span className="flex" aria-hidden>
        {[0, 1, 2, 3, 4].map((i) => (
          <Star
            key={i}
            className={cn("size-3.5", i < full ? "fill-star text-star" : "text-border")}
            strokeWidth={i < full ? 0 : 2}
          />
        ))}
      </span>
      <span className="tabular font-medium text-foreground" aria-hidden>
        {formatRating(rating)}
      </span>
      {count !== undefined && (
        <span className="tabular" aria-hidden>
          ({count.toLocaleString("pt-BR")})
        </span>
      )}
    </span>
  );
}

export function Kbd({ children }: { children: string }) {
  return (
    <kbd className="rounded-sm border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[0.7rem] text-muted">
      {children}
    </kbd>
  );
}
