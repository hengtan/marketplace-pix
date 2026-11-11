import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Marquee({
  items,
  className,
  label,
}: {
  items: ReactNode[];
  className?: string;
  label: string;
}) {
  const row = (hidden: boolean) => (
    <ul
      aria-hidden={hidden || undefined}
      className="flex shrink-0 items-center gap-10 pr-10"
      aria-label={hidden ? undefined : label}
    >
      {items.map((it, i) => (
        <li key={i} className="flex shrink-0 items-center gap-10">
          {it}
        </li>
      ))}
    </ul>
  );
  return (
    <div
      className={cn(
        "marquee relative overflow-hidden [mask-image:linear-gradient(to_right,transparent,black_12%,black_88%,transparent)]",
        className,
      )}
    >
      <div className="marquee-track">
        {row(false)}
        {row(true)}
      </div>
    </div>
  );
}
