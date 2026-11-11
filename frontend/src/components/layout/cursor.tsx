import { m, useMotionValue, useReducedMotion, useSpring } from "motion/react";
import { useEffect, useState } from "react";
import { finePointer } from "@/lib/motion";

const INTERACTIVE = "a, button, [role='button'], [role='radio'], summary, select, label[for]";

export function Cursor() {
  const reduce = useReducedMotion();
  const [on, setOn] = useState(false);
  const [mode, setMode] = useState<"idle" | "hover" | "label">("idle");
  const [label, setLabel] = useState("");
  const x = useMotionValue(-100);
  const y = useMotionValue(-100);
  const sx = useSpring(x, { stiffness: 520, damping: 40, mass: 0.4 });
  const sy = useSpring(y, { stiffness: 520, damping: 40, mass: 0.4 });

  useEffect(() => {
    if (reduce || !finePointer()) return;
    setOn(true);
    const move = (e: PointerEvent) => {
      x.set(e.clientX);
      y.set(e.clientY);
      const el = (e.target as Element | null)?.closest?.("[data-cursor]") as HTMLElement | null;
      if (el) {
        setMode("label");
        setLabel(el.dataset.cursor ?? "");
        return;
      }
      setMode((e.target as Element | null)?.closest?.(INTERACTIVE) ? "hover" : "idle");
    };
    const leave = () => setMode("idle");
    window.addEventListener("pointermove", move, { passive: true });
    document.documentElement.addEventListener("pointerleave", leave);
    return () => {
      window.removeEventListener("pointermove", move);
      document.documentElement.removeEventListener("pointerleave", leave);
    };
  }, [reduce, x, y]);

  if (!on) return null;
  return (
    <m.div
      aria-hidden
      className="pointer-events-none fixed top-0 left-0 z-[120] will-change-transform"
      style={{ x: sx, y: sy }}
    >
      <div className="-translate-x-1/2 -translate-y-1/2 relative grid size-[72px] place-items-center">
        <m.span
          className="absolute inset-0 rounded-full border border-primary/70"
          animate={{
            scale: mode === "label" ? 1 : mode === "hover" ? 0.62 : 0.2,
            backgroundColor:
              mode === "label" ? "oklch(0.5 0.25 270 / 0.92)" : "oklch(0.6 0.2 270 / 0.12)",
            opacity: mode === "idle" ? 0.7 : 1,
          }}
          transition={{ type: "spring", stiffness: 400, damping: 28 }}
        />
        <m.span
          className="relative text-[0.72rem] font-semibold text-white"
          animate={{ opacity: mode === "label" ? 1 : 0 }}
          transition={{ duration: 0.15 }}
        >
          {label}
        </m.span>
      </div>
    </m.div>
  );
}
