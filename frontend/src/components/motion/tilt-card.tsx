import {
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useSpring,
  useTransform,
} from "motion/react";
import { type ReactNode, useRef } from "react";
import { finePointer } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function TiltCard({
  children,
  className,
  max = 7,
  spotlight = true,
  glow = "oklch(0.7 0.2 270 / 0.22)",
}: {
  children: ReactNode;
  className?: string;
  max?: number;
  spotlight?: boolean;
  glow?: string;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const rect = useRef<DOMRect | null>(null);
  const px = useMotionValue(0.5);
  const py = useMotionValue(0.5);
  const sx = useSpring(px, { stiffness: 200, damping: 20 });
  const sy = useSpring(py, { stiffness: 200, damping: 20 });
  const rotateY = useTransform(sx, [0, 1], [-max, max]);
  const rotateX = useTransform(sy, [0, 1], [max, -max]);
  const gx = useTransform(px, (v) => `${v * 100}%`);
  const gy = useTransform(py, (v) => `${v * 100}%`);
  const bg = useMotionTemplate`radial-gradient(420px circle at ${gx} ${gy}, ${glow}, transparent 62%)`;
  const opacity = useMotionValue(0);
  const enabled = !reduce && finePointer();

  return (
    <div style={{ perspective: 900 }} className="h-full">
      <motion.div
        ref={ref}
        className={cn("group/tilt relative h-full", className)}
        style={enabled ? { rotateX, rotateY, transformStyle: "preserve-3d" } : undefined}
        onPointerEnter={() => {
          rect.current = ref.current?.getBoundingClientRect() ?? null;
          opacity.set(1);
        }}
        onPointerMove={(e) => {
          const r = rect.current;
          if (!enabled || !r) return;
          px.set((e.clientX - r.left) / r.width);
          py.set((e.clientY - r.top) / r.height);
        }}
        onPointerLeave={() => {
          px.set(0.5);
          py.set(0.5);
          opacity.set(0);
        }}
      >
        {children}
        {spotlight && enabled && (
          <motion.div
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-[inherit] transition-opacity duration-300"
            style={{ backgroundImage: bg, opacity }}
          />
        )}
      </motion.div>
    </div>
  );
}
