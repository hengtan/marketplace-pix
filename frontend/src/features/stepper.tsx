import { Check } from "lucide-react";
import { m } from "motion/react";
import { EASE, SPRING_POP } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol aria-label="Etapas da compra" className="flex items-center">
      {steps.map((label, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li
            key={label}
            aria-current={active ? "step" : undefined}
            className={cn("flex items-center", i < steps.length - 1 && "flex-1")}
          >
            <span className="flex items-center gap-3">
              <m.span
                layout
                initial={false}
                animate={{ scale: active ? 1.08 : 1 }}
                transition={SPRING_POP}
                className={cn(
                  "relative grid size-9 shrink-0 place-items-center rounded-full border text-sm font-bold",
                  done && "border-pix bg-pix text-[oklch(0.2_0.06_165)]",
                  active && "border-primary bg-primary text-primary-foreground shadow-glow",
                  !done && !active && "border-border-strong bg-surface text-muted",
                )}
              >
                {done ? <Check className="size-4" strokeWidth={3.2} /> : i + 1}
                {active && (
                  <span className="absolute inset-0 animate-[pulse-ring_2.4s_ease-out_infinite] rounded-full bg-primary/30" />
                )}
              </m.span>
              <span
                className={cn(
                  "hidden text-sm font-semibold sm:block",
                  active ? "text-foreground" : "text-muted",
                )}
              >
                {label}
              </span>
            </span>
            {i < steps.length - 1 && (
              <span className="relative mx-3 h-0.5 flex-1 overflow-hidden rounded-full bg-border sm:mx-5">
                <m.span
                  className="absolute inset-0 origin-left bg-pix"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: done ? 1 : 0 }}
                  transition={{ duration: 0.8, ease: EASE, delay: 0.2 }}
                />
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}
