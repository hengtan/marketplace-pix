import { animate, useInView, useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

export function AnimatedNumber({
  value,
  format,
  fromZero = false,
  duration = 0.9,
  className,
  testId,
  label,
}: {
  value: number;
  format: (n: number) => string;
  fromZero?: boolean;
  duration?: number;
  className?: string;
  testId?: string;
  label?: string;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -2% 0px" });
  const current = useRef(fromZero ? 0 : value);
  const fmt = useRef(format);
  fmt.current = format;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (reduce || (fromZero && !inView)) {
      current.current = reduce ? value : current.current;
      el.textContent = fmt.current(reduce ? value : current.current);
      return;
    }
    const controls = animate(current.current, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => {
        current.current = v;
        el.textContent = fmt.current(v);
      },
      onComplete: () => {
        current.current = value;
        el.textContent = fmt.current(value);
      },
    });
    return () => controls.stop();
  }, [value, reduce, fromZero, inView, duration]);

  return (
    <>
      <span ref={ref} aria-hidden data-testid={testId} className={cn("tabular", className)}>
        {format(fromZero ? 0 : value)}
      </span>
      <span className="sr-only">{label ?? format(value)}</span>
    </>
  );
}
