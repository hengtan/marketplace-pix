import { m } from "motion/react";
import { type KeyboardEvent, useRef } from "react";
import { MERCHANT_TABS, type MerchantTab } from "@/lib/merchant-metrics";
import { SPRING } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function tabId(tab: MerchantTab) {
  return `aba-${tab}`;
}

export function panelId(tab: MerchantTab) {
  return `painel-${tab}`;
}

export function TabBar({
  active,
  onChange,
  badges,
}: {
  active: MerchantTab;
  onChange: (tab: MerchantTab) => void;
  badges: Partial<Record<MerchantTab, { count: number; label: string; tone: "warn" | "danger" }>>;
}) {
  const refs = useRef<Partial<Record<MerchantTab, HTMLButtonElement | null>>>({});

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const index = MERCHANT_TABS.findIndex((t) => t.id === active);
    const last = MERCHANT_TABS.length - 1;
    const next =
      e.key === "ArrowRight"
        ? (index + 1) % MERCHANT_TABS.length
        : e.key === "ArrowLeft"
          ? (index - 1 + MERCHANT_TABS.length) % MERCHANT_TABS.length
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? last
              : -1;
    if (next < 0) return;
    e.preventDefault();
    const tab = MERCHANT_TABS[next]?.id;
    if (!tab) return;
    onChange(tab);
    refs.current[tab]?.focus();
  };

  return (
    <div className="-mx-4 overflow-x-auto px-4 pb-1 hide-scrollbar sm:mx-0 sm:px-0">
      <div
        role="tablist"
        aria-label="Seções do painel"
        onKeyDown={onKeyDown}
        className="glass inline-flex min-w-max gap-1 rounded-full p-1"
      >
        {MERCHANT_TABS.map((t) => {
          const selected = t.id === active;
          const badge = badges[t.id];
          return (
            <button
              key={t.id}
              ref={(el) => {
                refs.current[t.id] = el;
              }}
              type="button"
              role="tab"
              id={tabId(t.id)}
              aria-selected={selected}
              aria-controls={panelId(t.id)}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(t.id)}
              className={cn(
                "relative flex h-11 items-center gap-2 rounded-full px-4 text-sm font-medium transition-colors",
                selected ? "text-background" : "text-muted hover:text-foreground",
              )}
            >
              {selected && (
                <m.span
                  layoutId="merchant-tab-pill"
                  className="absolute inset-0 rounded-full bg-foreground"
                  transition={SPRING}
                />
              )}
              <span className="relative">{t.label}</span>
              {badge && badge.count > 0 && (
                <span
                  className={cn(
                    "tabular relative grid min-w-5 place-items-center rounded-full px-1.5 text-[0.7rem] leading-5 font-bold",
                    badge.tone === "danger"
                      ? "bg-danger text-primary-foreground"
                      : "bg-sun text-[oklch(0.2_0.06_55)]",
                  )}
                >
                  <span aria-hidden>{badge.count}</span>
                  <span className="sr-only">{badge.label}</span>
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
