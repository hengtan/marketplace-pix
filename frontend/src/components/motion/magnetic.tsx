import { m, useMotionValue, useReducedMotion, useSpring } from "motion/react";
import { type ReactNode, useRef } from "react";
import { finePointer } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function Magnetic({
  children,
  strength = 0.28,
  className,
}: {
  children: ReactNode;
  strength?: number;
  className?: string;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 220, damping: 16, mass: 0.4 });
  const sy = useSpring(y, { stiffness: 220, damping: 16, mass: 0.4 });
  const rect = useRef<DOMRect | null>(null);
  const enabled = !reduce && finePointer();

  return (
    <m.span
      ref={ref}
      className={cn("inline-flex", className)}
      style={enabled ? { x: sx, y: sy } : undefined}
      onPointerEnter={() => {
        rect.current = ref.current?.getBoundingClientRect() ?? null;
      }}
      onPointerMove={(e) => {
        const r = rect.current;
        if (!enabled || !r) return;
        x.set((e.clientX - (r.left + r.width / 2)) * strength);
        y.set((e.clientY - (r.top + r.height / 2)) * strength);
      }}
      onPointerLeave={() => {
        x.set(0);
        y.set(0);
      }}
    >
      {children}
    </m.span>
  );
}
