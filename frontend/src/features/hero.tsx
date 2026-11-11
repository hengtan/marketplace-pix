import { Sparkles } from "lucide-react";
import {
  motion,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
} from "motion/react";
import { type ReactNode, useEffect, useRef } from "react";
import { AnimatedNumber } from "@/components/motion/animated-number";
import { Magnetic } from "@/components/motion/magnetic";
import { SplitWords } from "@/components/motion/reveal";
import { ProductImage } from "@/components/product-image";
import { Button } from "@/components/ui/button";
import { formatMoney } from "@/lib/format";
import { EASE, finePointer } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { useUi } from "@/store/ui";

type MV = ReturnType<typeof useSpring>;

function Layer({
  depth,
  sx,
  sy,
  className,
  children,
  delay = 0,
}: {
  depth: number;
  sx: MV;
  sy: MV;
  className?: string;
  children: ReactNode;
  delay?: number;
}) {
  const x = useTransform(sx, (v) => v * depth);
  const y = useTransform(sy, (v) => v * depth);
  return (
    <motion.div className={cn("absolute will-change-transform", className)} style={{ x, y }}>
      <motion.div
        initial={{ opacity: 0, y: 28, scale: 0.94 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 1, delay, ease: EASE }}
        className="h-full w-full"
      >
        {children}
      </motion.div>
    </motion.div>
  );
}

function Chip({ children, tone = "surface" }: { children: ReactNode; tone?: "surface" | "pix" }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      animate={reduce ? undefined : { y: [0, -7, 0] }}
      transition={{ duration: 5, repeat: Number.POSITIVE_INFINITY, ease: "easeInOut" }}
      className={cn(
        "glass flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold whitespace-nowrap shadow-lift",
        tone === "pix" && "!bg-pix !text-[oklch(0.2_0.06_165)]",
      )}
    >
      {children}
    </motion.div>
  );
}

function Receipt() {
  const reduce = useReducedMotion();
  return (
    <div className="glass hairline-top overflow-hidden rounded-3xl p-5 shadow-lift">
      <div className="flex items-center justify-between text-xs font-medium text-muted">
        <span className="tabular">Pedido 7F3A91C2</span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-1.5 rounded-full bg-pix" /> ao vivo
        </span>
      </div>
      <p className="tabular mt-4 font-display text-[2.6rem] leading-none font-bold tracking-[-0.04em]">
        {formatMoney(34990)}
      </p>
      <div className="mt-5 flex items-center gap-3 rounded-2xl bg-pix px-4 py-3 text-[oklch(0.2_0.06_165)]">
        <span className="relative grid size-9 place-items-center rounded-full bg-[oklch(0.2_0.06_165)] text-pix">
          <span className="absolute inset-0 animate-[pulse-ring_2.4s_ease-out_infinite] rounded-full bg-[oklch(0.2_0.06_165)]/35" />
          <svg
            viewBox="0 0 24 24"
            className="relative size-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="3.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden
          >
            <motion.path
              d="M5 12.5l4.5 4.5L19 7.5"
              initial={reduce ? false : { pathLength: 0 }}
              animate={{ pathLength: [0, 1, 1, 0] }}
              transition={{
                duration: 4,
                times: [0, 0.2, 0.85, 1],
                repeat: Number.POSITIVE_INFINITY,
                repeatDelay: 0.6,
                delay: 1.4,
              }}
            />
          </svg>
        </span>
        <span className="font-semibold">PIX confirmado em 2 s</span>
      </div>
    </div>
  );
}

function Scene({ sx, sy }: { sx: MV; sy: MV }) {
  return (
    <div className="relative mx-auto aspect-[5/4] w-full max-w-[34rem]" aria-hidden>
      <div className="absolute inset-[6%] rounded-full border border-border-strong/50" />
      <div className="absolute inset-[18%] rounded-full border border-dashed border-border-strong/40" />
      <Layer
        depth={14}
        sx={sx}
        sy={sy}
        delay={0.5}
        className="top-[2%] left-[2%] w-[44%] -rotate-[7deg]"
      >
        <ProductImage
          src={null}
          alt=""
          category="tecnologia"
          seed="fone-bluetooth-nova"
          className="rounded-[1.75rem] shadow-lift ring-1 ring-white/30"
          float
        />
      </Layer>
      <Layer
        depth={30}
        sx={sx}
        sy={sy}
        delay={0.65}
        className="top-[8%] right-[2%] w-[40%] rotate-[6deg]"
      >
        <ProductImage
          src={null}
          alt=""
          category="casa"
          seed="luminaria-arco-dourado"
          className="rounded-[1.75rem] shadow-lift ring-1 ring-white/30"
          float
        />
      </Layer>
      <Layer
        depth={-10}
        sx={sx}
        sy={sy}
        delay={0.8}
        className="top-[40%] left-[38%] w-[26%] rotate-[-3deg]"
      >
        <ProductImage
          src={null}
          alt=""
          category="esporte"
          seed="tenis-corrida-vento"
          className="rounded-[1.4rem] shadow-lift ring-1 ring-white/30"
          float
        />
      </Layer>
      <Layer
        depth={44}
        sx={sx}
        sy={sy}
        delay={0.95}
        className="bottom-[2%] left-[10%] w-[68%] -rotate-[2deg]"
      >
        <Receipt />
      </Layer>
      <Layer depth={58} sx={sx} sy={sy} delay={1.2} className="top-[40%] -right-[2%]">
        <Chip>Estoque reservado</Chip>
      </Layer>
      <Layer depth={64} sx={sx} sy={sy} delay={1.35} className="bottom-[34%] -left-[3%]">
        <Chip tone="pix">+ {formatMoney(31491)} no saldo</Chip>
      </Layer>
    </div>
  );
}

export function Hero({
  productCount,
  merchantCount,
}: {
  productCount: number;
  merchantCount: number;
}) {
  const reduce = useReducedMotion();
  const ref = useRef<HTMLElement>(null);
  const setAssistantOpen = useUi((s) => s.setAssistantOpen);
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const sx = useSpring(mx, { stiffness: 70, damping: 16 });
  const sy = useSpring(my, { stiffness: 70, damping: 16 });
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end start"] });
  const textY = useTransform(scrollYProgress, [0, 1], [0, 90]);
  const sceneY = useTransform(scrollYProgress, [0, 1], [0, -70]);
  const fade = useTransform(scrollYProgress, [0, 0.8], [1, 0]);

  useEffect(() => {
    if (reduce || !finePointer()) return;
    const el = ref.current;
    if (!el) return;
    const move = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      mx.set(((e.clientX - r.left) / r.width - 0.5) * -1);
      my.set(((e.clientY - r.top) / r.height - 0.5) * -1);
    };
    el.addEventListener("pointermove", move, { passive: true });
    return () => el.removeEventListener("pointermove", move);
  }, [reduce, mx, my]);

  return (
    <section ref={ref} className="relative isolate overflow-hidden" aria-labelledby="hero-title">
      <div className="aurora" aria-hidden>
        <i />
        <i />
        <i />
      </div>
      <div className="grid-lines pointer-events-none absolute inset-0 -z-10" aria-hidden />
      <div className="mx-auto grid max-w-7xl items-center gap-8 px-4 pt-8 pb-16 sm:px-6 md:pt-14 lg:grid-cols-[1.1fr_1fr] lg:pb-24">
        <motion.div style={reduce ? undefined : { y: textY, opacity: fade }}>
          <motion.p
            initial={reduce ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease: EASE }}
            className="glass inline-flex items-center gap-2.5 rounded-full py-1.5 pr-4 pl-2 text-sm font-medium"
          >
            <span className="grid size-6 place-items-center rounded-full bg-pix text-[oklch(0.2_0.06_165)]">
              <span className="size-2 animate-pulse rounded-full bg-current" />
            </span>
            PIX com confirmação em tempo real
          </motion.p>
          <h1 id="hero-title" className="text-display mt-6">
            <SplitWords text="Compre hoje." delay={0.1} />
            <br />
            <SplitWords text="Pague em" delay={0.25} />{" "}
            <SplitWords text="segundos." delay={0.4} italicFrom={0} className="text-primary" />
          </h1>
          <motion.p
            className="mt-7 max-w-[36ch] text-lg text-muted sm:text-xl"
            initial={reduce ? false : { opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.55, ease: EASE }}
          >
            Produtos de lojistas independentes, estoque conferido em tempo real e pagamento por PIX
            que confirma na hora.
          </motion.p>
          <motion.div
            className="mt-9 flex flex-wrap items-center gap-3"
            initial={reduce ? false : { opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.7, ease: EASE }}
          >
            <Magnetic>
              <Button asChild size="lg">
                <a href="#vitrine">Explorar a vitrine</a>
              </Button>
            </Magnetic>
            <Magnetic>
              <Button variant="outline" size="lg" onClick={() => setAssistantOpen(true)}>
                <Sparkles /> Perguntar ao assistente
              </Button>
            </Magnetic>
          </motion.div>
          <motion.dl
            className="mt-12 grid max-w-md grid-cols-3 gap-6 border-t border-border pt-6"
            initial={reduce ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, delay: 1 }}
          >
            {[
              { v: productCount, l: "produtos" },
              { v: merchantCount, l: "lojistas" },
              { v: 2, l: "segundos no PIX", suffix: " s" },
            ].map((s) => (
              <div key={s.l}>
                <dd className="font-display text-3xl font-bold tracking-tight">
                  <AnimatedNumber
                    value={s.v}
                    format={(n) => `${Math.round(n)}${s.suffix ?? ""}`}
                    fromZero
                  />
                </dd>
                <dt className="text-sm text-muted">{s.l}</dt>
              </div>
            ))}
          </motion.dl>
        </motion.div>
        <motion.div style={reduce ? undefined : { y: sceneY }}>
          <Scene sx={sx} sy={sy} />
        </motion.div>
      </div>
    </section>
  );
}
