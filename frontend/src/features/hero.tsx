import { Check, QrCode } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";

const LINES = ["Compre hoje.", "Pague em", "segundos."];

export function Hero() {
  const reduce = useReducedMotion();
  return (
    <section className="relative isolate overflow-hidden" aria-labelledby="hero-title">
      <div className="mx-auto grid max-w-7xl gap-10 px-4 pt-10 pb-12 sm:px-6 md:pt-16 lg:grid-cols-[1.35fr_1fr] lg:items-end">
        <div>
          <h1
            id="hero-title"
            className="text-[clamp(2.9rem,7.6vw,6.5rem)] leading-[0.94] whitespace-nowrap font-bold tracking-[-0.045em]"
          >
            {LINES.map((line, i) => (
              <span key={line} className="block overflow-hidden pb-[0.08em]">
                <motion.span
                  className="block"
                  initial={reduce ? false : { y: "105%" }}
                  animate={{ y: 0 }}
                  transition={{ duration: 0.9, delay: 0.08 * i, ease: [0.16, 1, 0.3, 1] }}
                >
                  {line}
                </motion.span>
              </span>
            ))}
          </h1>
          <motion.p
            className="mt-6 max-w-[34ch] text-lg text-muted sm:text-xl"
            initial={reduce ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, delay: 0.5, ease: [0.16, 1, 0.3, 1] }}
          >
            Produtos de lojistas independentes, estoque conferido em tempo real e confirmação do PIX
            na hora.
          </motion.p>
        </div>

        <motion.div
          aria-hidden
          className="relative mx-auto w-full max-w-sm lg:mr-0"
          initial={reduce ? false : { opacity: 0, y: 24, rotate: 2 }}
          animate={{ opacity: 1, y: 0, rotate: -2 }}
          transition={{ duration: 1, delay: 0.35, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="rounded-xl bg-foreground p-5 text-background shadow-lift">
            <div className="flex items-center justify-between text-sm opacity-70">
              <span>Pedido 7F3A91C2</span>
              <QrCode className="size-5" />
            </div>
            <p className="tabular mt-6 font-display text-5xl font-bold tracking-tight">R$ 349,90</p>
            <div className="mt-6 flex items-center gap-3 rounded-lg bg-pix px-4 py-3 text-[oklch(0.2_0.06_165)]">
              <span className="relative size-8">
                <span className="absolute inset-0 animate-[pulse-ring_2.4s_ease-out_infinite] rounded-full bg-[oklch(0.2_0.06_165)]/40" />
                <span className="relative grid size-8 place-items-center rounded-full bg-[oklch(0.2_0.06_165)] text-pix">
                  <Check className="size-4" strokeWidth={3} />
                </span>
              </span>
              <span className="font-semibold">PIX confirmado em 2 s</span>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
