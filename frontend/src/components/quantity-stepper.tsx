import { Minus, Plus } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { SPRING } from "@/lib/motion";
import { cn } from "@/lib/utils";

interface Props {
  value: number;
  min?: number;
  max: number;
  onChange: (value: number) => void;
  label: string;
  className?: string;
  size?: "sm" | "md";
}

export function QuantityStepper({
  value,
  min = 0,
  max,
  onChange,
  label,
  className,
  size = "md",
}: Props) {
  const btn = cn(
    "grid place-items-center rounded-full text-foreground transition-colors hover:bg-primary-soft hover:text-primary disabled:opacity-40 disabled:hover:bg-transparent",
    size === "md" ? "size-10" : "size-9",
  );
  return (
    <fieldset
      className={cn(
        "inline-flex items-center rounded-full border border-border bg-surface p-0.5",
        className,
      )}
      aria-label={label}
    >
      <button
        type="button"
        className={btn}
        onClick={() => onChange(value - 1)}
        disabled={value <= min}
        aria-label={`Diminuir quantidade de ${label}`}
      >
        <Minus className="size-4" />
      </button>
      <output
        className="tabular relative grid h-6 min-w-8 place-items-center overflow-hidden text-center text-sm font-semibold"
        aria-live="polite"
      >
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.span
            key={value}
            initial={{ y: 14, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -14, opacity: 0 }}
            transition={SPRING}
          >
            {value}
          </motion.span>
        </AnimatePresence>
      </output>
      <button
        type="button"
        className={btn}
        onClick={() => onChange(value + 1)}
        disabled={value >= max}
        aria-label={`Aumentar quantidade de ${label}`}
      >
        <Plus className="size-4" />
      </button>
    </fieldset>
  );
}
