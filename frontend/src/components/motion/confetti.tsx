import { motion, useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";

const COLORS = [
  "var(--primary)",
  "var(--pix)",
  "var(--sun)",
  "oklch(0.72 0.2 330)",
  "oklch(0.85 0.14 95)",
];

function rand(seed: number) {
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}

export function Confetti({
  count = 64,
  origin = { x: 50, y: 38 },
}: {
  count?: number;
  origin?: { x: number; y: number };
}) {
  const reduce = useReducedMotion();
  const [alive, setAlive] = useState(true);
  useEffect(() => {
    const t = setTimeout(() => setAlive(false), 3800);
    return () => clearTimeout(t);
  }, []);
  const pieces = useMemo(
    () =>
      Array.from({ length: count }, (_, i) => {
        const angle = (rand(i + 1) * 1.1 + 0.2) * Math.PI;
        const power = 280 + rand(i + 7) * 520;
        return {
          id: i,
          x: Math.cos(angle) * power * (rand(i + 3) > 0.5 ? 1 : -1) * 0.8,
          up: -Math.abs(Math.sin(angle)) * power * 0.9,
          fall: 380 + rand(i + 5) * 380,
          rotate: (rand(i + 9) - 0.5) * 900,
          size: 6 + rand(i + 11) * 8,
          color: COLORS[i % COLORS.length],
          round: rand(i + 13) > 0.65,
          delay: rand(i + 15) * 0.12,
        };
      }),
    [count],
  );
  if (reduce || !alive) return null;
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 z-[90] overflow-hidden">
      {pieces.map((p) => (
        <motion.span
          key={p.id}
          className="absolute will-change-transform"
          style={{
            left: `${origin.x}%`,
            top: `${origin.y}%`,
            width: p.size,
            height: p.round ? p.size : p.size * 0.45,
            background: p.color,
            borderRadius: p.round ? "50%" : 2,
          }}
          initial={{ x: 0, y: 0, opacity: 1, rotate: 0, scale: 0.4 }}
          animate={{
            x: [0, p.x * 0.7, p.x],
            y: [0, p.up, p.up + p.fall],
            rotate: p.rotate,
            opacity: [1, 1, 0],
            scale: [0.4, 1, 0.9],
          }}
          transition={{
            duration: 2.6,
            delay: p.delay,
            ease: [0.2, 0.7, 0.3, 1],
            times: [0, 0.35, 1],
          }}
        />
      ))}
    </div>
  );
}
