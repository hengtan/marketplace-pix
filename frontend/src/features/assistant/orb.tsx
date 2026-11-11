import { motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";

export function Orb({
  className,
  thinking = false,
  particles = false,
}: {
  className?: string;
  thinking?: boolean;
  particles?: boolean;
}) {
  const reduce = useReducedMotion();
  return (
    <span aria-hidden className={cn("relative grid size-8 shrink-0 place-items-center", className)}>
      {thinking && !reduce && (
        <span className="absolute inset-0 animate-[pulse-ring_1.8s_ease-out_infinite] rounded-full bg-primary/35" />
      )}
      <span className="absolute inset-0 overflow-hidden rounded-full shadow-[0_0_18px_-2px_oklch(0.6_0.22_280/0.6),inset_0_1px_1px_oklch(1_0_0/0.5)]">
        <motion.span
          className="absolute -inset-1/2 will-change-transform [background:conic-gradient(from_0deg,oklch(0.7_0.2_275),oklch(0.78_0.17_165),oklch(0.75_0.17_55),oklch(0.65_0.24_320),oklch(0.7_0.2_275))]"
          animate={reduce ? undefined : { rotate: 360 }}
          transition={{
            duration: thinking ? 2.2 : 9,
            repeat: Number.POSITIVE_INFINITY,
            ease: "linear",
          }}
        />
        <span className="absolute inset-[12%] rounded-full bg-[radial-gradient(circle_at_30%_25%,oklch(1_0_0/0.85),oklch(1_0_0/0.15)_55%,transparent_70%)]" />
      </span>
      {particles && !reduce && (
        <>
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <span
              key={i}
              className="absolute size-1 rounded-full bg-primary/70 [animation:float_4s_ease-in-out_infinite]"
              style={{
                left: `${10 + i * 15}%`,
                top: `${-20 - (i % 3) * 14}%`,
                animationDelay: `${i * 0.6}s`,
                opacity: 0.4 + (i % 3) * 0.2,
              }}
            />
          ))}
        </>
      )}
    </span>
  );
}
