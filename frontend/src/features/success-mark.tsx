import { motion, useReducedMotion } from "motion/react";

const SPARKS = Array.from({ length: 12 }, (_, i) => i);

export function SuccessMark() {
  const reduce = useReducedMotion();
  return (
    <div className="relative mx-auto grid size-32 place-items-center" aria-hidden>
      {!reduce &&
        SPARKS.map((i) => {
          const angle = (i / SPARKS.length) * Math.PI * 2;
          return (
            <motion.span
              key={i}
              className="absolute size-2 rounded-full"
              style={{ background: i % 3 === 0 ? "var(--primary)" : "var(--pix)" }}
              initial={{ x: 0, y: 0, opacity: 0, scale: 0.4 }}
              animate={{
                x: Math.cos(angle) * 74,
                y: Math.sin(angle) * 74,
                opacity: [0, 1, 0],
                scale: [0.4, 1, 0.6],
              }}
              transition={{ duration: 1.1, delay: 0.35, ease: [0.16, 1, 0.3, 1] }}
            />
          );
        })}
      <motion.div
        className="grid size-24 place-items-center rounded-full bg-pix"
        initial={reduce ? false : { scale: 0.3, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 18 }}
      >
        <svg viewBox="0 0 24 24" className="size-12" fill="none" stroke="oklch(0.2 0.06 165)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
          <motion.path
            d="M5 12.5l4.5 4.5L19 7.5"
            initial={reduce ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.5, delay: 0.25, ease: "easeOut" }}
          />
        </svg>
      </motion.div>
    </div>
  );
}
