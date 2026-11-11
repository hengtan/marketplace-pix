import { Link } from "@tanstack/react-router";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";

export function Mark({ className }: { className?: string }) {
  const reduce = useReducedMotion();
  return (
    <svg viewBox="0 0 32 32" className={cn("size-9", className)} aria-hidden>
      <defs>
        <linearGradient id="mark-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="oklch(0.62 0.24 275)" />
          <stop offset="1" stopColor="oklch(0.42 0.26 268)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="10" fill="url(#mark-g)" />
      <rect width="32" height="32" rx="10" fill="none" stroke="white" strokeOpacity="0.25" />
      <path
        d="M10.5 23V9h6.5a4.5 4.5 0 0 1 0 9h-3"
        fill="none"
        stroke="white"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <motion.circle
        cx="23"
        cy="22.5"
        r="2.4"
        className="fill-pix"
        animate={reduce ? undefined : { scale: [1, 1.35, 1] }}
        transition={{ duration: 2.4, repeat: Number.POSITIVE_INFINITY, ease: "easeInOut" }}
        style={{ transformOrigin: "23px 22.5px" }}
      />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <Link
      to="/"
      className={cn("group flex items-center gap-2.5 rounded-xl", className)}
      aria-label="Praça, página inicial"
    >
      <Mark className="transition-transform duration-500 group-hover:rotate-[-8deg] group-hover:scale-105" />
      <span className="font-display text-[1.65rem] font-bold tracking-[-0.04em]">Praça</span>
    </Link>
  );
}
