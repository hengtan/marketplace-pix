import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";
import { EASE } from "@/lib/motion";

export type ArtName = "cart" | "search" | "orders" | "error" | "lost" | "pix";

function Draw({
  d,
  delay = 0,
  className,
  strokeWidth = 3,
}: {
  d: string;
  delay?: number;
  className?: string;
  strokeWidth?: number;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.path
      d={d}
      fill="none"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      initial={reduce ? false : { pathLength: 0, opacity: 0 }}
      animate={{ pathLength: 1, opacity: 1 }}
      transition={{ duration: 1.1, delay, ease: EASE }}
    />
  );
}

function Bob({
  children,
  delay = 0,
  amp = 5,
}: {
  children: ReactNode;
  delay?: number;
  amp?: number;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.g
      animate={reduce ? undefined : { y: [0, -amp, 0] }}
      transition={{ duration: 4.5, repeat: Number.POSITIVE_INFINITY, ease: "easeInOut", delay }}
    >
      {children}
    </motion.g>
  );
}

function Spark({
  x,
  y,
  delay = 0,
  tone = "sun",
}: {
  x: number;
  y: number;
  delay?: number;
  tone?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.path
      d={`M${x} ${y - 6}v12M${x - 6} ${y}h12`}
      strokeWidth="2.4"
      strokeLinecap="round"
      className={
        tone === "pix" ? "stroke-pix" : tone === "primary" ? "stroke-primary" : "stroke-sun"
      }
      style={{ transformOrigin: `${x}px ${y}px` }}
      animate={reduce ? undefined : { scale: [0.6, 1.15, 0.6], opacity: [0.4, 1, 0.4] }}
      transition={{ duration: 2.8, repeat: Number.POSITIVE_INFINITY, delay }}
    />
  );
}

const SCENES: Record<ArtName, ReactNode> = {
  cart: (
    <>
      <ellipse cx="80" cy="108" rx="44" ry="6" className="fill-foreground/10" />
      <Bob>
        <Draw d="M34 30h14l10 44h46l10-32H52" className="stroke-primary" strokeWidth={4} />
        <Draw d="M58 74l-3 12h58" className="stroke-primary" strokeWidth={4} delay={0.15} />
        <circle cx="64" cy="96" r="6" className="fill-foreground" />
        <circle cx="102" cy="96" r="6" className="fill-foreground" />
        <motion.rect
          x="68"
          y="48"
          width="16"
          height="16"
          rx="4"
          className="fill-pix"
          initial={{ y: -16, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ delay: 0.7, type: "spring", stiffness: 300, damping: 14 }}
        />
      </Bob>
      <Spark x={130} y={34} />
      <Spark x={28} y={70} delay={1} tone="pix" />
    </>
  ),
  search: (
    <>
      <ellipse cx="80" cy="108" rx="40" ry="6" className="fill-foreground/10" />
      <Bob>
        <Draw d="M58 40a24 24 0 1 0 0.1 0z" className="stroke-primary" strokeWidth={5} />
        <Draw d="M76 62l24 24" className="stroke-primary" strokeWidth={7} delay={0.3} />
        <Draw d="M50 42q8-8 18-4" className="stroke-pix" strokeWidth={3} delay={0.5} />
      </Bob>
      <Spark x={118} y={36} />
      <Spark x={34} y={88} delay={0.8} tone="primary" />
      <Spark x={126} y={80} delay={1.4} tone="pix" />
    </>
  ),
  orders: (
    <>
      <ellipse cx="80" cy="108" rx="42" ry="6" className="fill-foreground/10" />
      <Bob>
        <rect
          x="46"
          y="22"
          width="68"
          height="82"
          rx="10"
          className="fill-surface stroke-border-strong"
          strokeWidth="2"
        />
        <Draw
          d="M58 42h44M58 56h44M58 70h26"
          className="stroke-primary"
          strokeWidth={4}
          delay={0.2}
        />
        <Draw d="M58 88l6 6 12-14" className="stroke-pix" strokeWidth={5} delay={0.8} />
        <path
          d="M46 104l7 -6 7 6 7-6 7 6 7-6 7 6 7-6 7 6"
          fill="none"
          className="stroke-border-strong"
          strokeWidth="2"
        />
      </Bob>
      <Spark x={128} y={30} />
      <Spark x={30} y={60} delay={1.2} tone="pix" />
    </>
  ),
  error: (
    <>
      <ellipse cx="80" cy="108" rx="40" ry="6" className="fill-foreground/10" />
      <Bob amp={3}>
        <Draw d="M80 24L130 98H30z" className="stroke-danger" strokeWidth={5} />
        <Draw d="M80 52v22" className="stroke-danger" strokeWidth={6} delay={0.6} />
        <motion.circle
          cx="80"
          cy="86"
          r="3.5"
          className="fill-danger"
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ delay: 1, type: "spring", stiffness: 500, damping: 12 }}
        />
      </Bob>
      <Spark x={136} y={40} />
      <Spark x={26} y={52} delay={1} tone="primary" />
    </>
  ),
  lost: (
    <>
      <ellipse cx="80" cy="106" rx="34" ry="6" className="fill-foreground/10" />
      <motion.ellipse
        cx="80"
        cy="106"
        rx="34"
        ry="6"
        fill="none"
        className="stroke-primary"
        strokeWidth="2"
        animate={{ scale: [0.6, 1.5], opacity: [0.7, 0] }}
        transition={{ duration: 2.4, repeat: Number.POSITIVE_INFINITY }}
        style={{ transformOrigin: "80px 106px" }}
      />
      <Bob>
        <Draw
          d="M80 100C58 74 52 62 52 50a28 28 0 0 1 56 0c0 12-6 24-28 50z"
          className="stroke-primary"
          strokeWidth={5}
        />
        <motion.circle
          cx="80"
          cy="50"
          r="9"
          className="fill-pix"
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{ delay: 0.8, type: "spring", stiffness: 400, damping: 12 }}
        />
      </Bob>
      <Spark x={126} y={32} />
      <Spark x={30} y={40} delay={0.9} tone="pix" />
    </>
  ),
  pix: (
    <>
      <Bob>
        <rect
          x="46"
          y="26"
          width="68"
          height="68"
          rx="14"
          className="fill-surface stroke-primary"
          strokeWidth="3"
        />
        {[0, 1, 2].map((r) =>
          [0, 1, 2].map((c) => (
            <motion.rect
              key={`${r}-${c}`}
              x={58 + c * 16}
              y={38 + r * 16}
              width="10"
              height="10"
              rx="2.5"
              className={(r + c) % 2 === 0 ? "fill-primary" : "fill-pix"}
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.15 * (r + c), type: "spring", stiffness: 400, damping: 15 }}
              style={{ transformOrigin: `${63 + c * 16}px ${43 + r * 16}px` }}
            />
          )),
        )}
      </Bob>
      <Spark x={126} y={34} tone="pix" />
    </>
  ),
};

export function Illustration({ name, className = "h-36" }: { name: ArtName; className?: string }) {
  return (
    <svg
      viewBox="0 0 160 120"
      className={className}
      aria-hidden
      focusable="false"
      role="presentation"
    >
      <circle cx="80" cy="62" r="52" className="fill-primary-soft" opacity="0.7" />
      {SCENES[name]}
    </svg>
  );
}
