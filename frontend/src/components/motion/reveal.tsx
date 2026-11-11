import { motion, useReducedMotion } from "motion/react";
import type { ComponentProps, ElementType, ReactNode } from "react";
import { EASE, rise, stagger } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function Reveal({
  children,
  delay = 0,
  className,
  y = 22,
  as = "div",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  y?: number;
  as?: "div" | "section" | "li" | "p" | "span";
}) {
  const reduce = useReducedMotion();
  const Comp = motion[as] as ElementType;
  return (
    <Comp
      className={className}
      initial={reduce ? false : { opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "0px 0px -8% 0px" }}
      transition={{ duration: 0.8, delay, ease: EASE }}
    >
      {children}
    </Comp>
  );
}

export function Stagger({
  children,
  step = 0.06,
  delay = 0,
  className,
  as = "div",
  inView = true,
  ...rest
}: {
  children: ReactNode;
  step?: number;
  delay?: number;
  className?: string;
  as?: "div" | "ul" | "ol" | "section" | "dl";
  inView?: boolean;
} & Omit<ComponentProps<"div">, "children" | "className">) {
  const reduce = useReducedMotion();
  const Comp = motion[as] as ElementType;
  const trigger = inView
    ? { whileInView: "show", viewport: { once: true, margin: "0px 0px -6% 0px" } }
    : { animate: "show" };
  return (
    <Comp
      className={className}
      variants={stagger(step, delay)}
      initial={reduce ? "show" : "hidden"}
      {...trigger}
      {...rest}
    >
      {children}
    </Comp>
  );
}

export function StaggerItem({
  children,
  className,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "li" | "article" | "dd";
}) {
  const Comp = motion[as] as ElementType;
  return (
    <Comp className={className} variants={rise}>
      {children}
    </Comp>
  );
}

export function SplitWords({
  text,
  className,
  delay = 0,
  step = 0.055,
  as: Tag = "span",
  italicFrom,
}: {
  text: string;
  className?: string;
  delay?: number;
  step?: number;
  as?: "span" | "h1" | "h2";
  italicFrom?: number;
}) {
  const reduce = useReducedMotion();
  const words = text.split(" ");
  return (
    <Tag className={className}>
      <span className="sr-only">{text}</span>
      <span aria-hidden className="inline">
        {words.map((w, i) => (
          <span key={`${w}-${i}`} className="inline-block overflow-hidden pb-[0.14em] align-bottom">
            <motion.span
              className={cn(
                "inline-block will-change-transform",
                italicFrom !== undefined && i >= italicFrom && "serif pr-[0.06em] font-normal",
              )}
              initial={reduce ? false : { y: "112%", rotate: 4 }}
              animate={{ y: 0, rotate: 0 }}
              transition={{ duration: 1, delay: delay + i * step, ease: EASE }}
            >
              {w}
              {i < words.length - 1 ? " " : ""}
            </motion.span>
          </span>
        ))}
      </span>
    </Tag>
  );
}
