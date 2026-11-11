import { Link } from "@tanstack/react-router";
import { Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { AnimatedNumber } from "@/components/motion/animated-number";
import { useStock } from "@/hooks/queries";
import { formatMoney, pluralize } from "@/lib/format";
import { SPRING } from "@/lib/motion";
import { MAX_PER_ITEM, selectCount, selectSubtotal, useCart } from "@/store/cart";
import { useUi } from "@/store/ui";
import { Illustration } from "./illustrations";
import { ProductImage } from "./product-image";
import { QuantityStepper } from "./quantity-stepper";
import { Button } from "./ui/button";
import { Dialog, DialogContent } from "./ui/dialog";

export function CartLines({ compact = false }: { compact?: boolean }) {
  const lines = useCart((s) => s.lines);
  const setQuantity = useCart((s) => s.setQuantity);
  const remove = useCart((s) => s.remove);
  const { data: stock } = useStock(lines.map((l) => l.productId));

  return (
    <ul className="grid">
      <AnimatePresence initial={false} mode="popLayout">
        {lines.map((line) => {
          const available = stock?.[line.productId];
          const max = Math.min(MAX_PER_ITEM, available ?? MAX_PER_ITEM);
          return (
            <motion.li
              key={line.productId}
              layout="position"
              initial={{ opacity: 0, x: 40 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -60, scale: 0.9 }}
              transition={SPRING}
              className="grid grid-cols-[4.5rem_1fr] gap-4 pb-5"
              data-testid="cart-line"
            >
              <Link to="/produto/$slug" params={{ slug: line.slug }} className="block">
                <ProductImage
                  src={line.imageUrl}
                  alt=""
                  category={line.category}
                  seed={line.slug}
                  className="rounded-2xl"
                  size={144}
                />
              </Link>
              <div className="min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-xs text-muted">{line.merchantName}</p>
                    <p className="line-clamp-2 text-sm leading-snug font-semibold">{line.name}</p>
                  </div>
                  {!compact && (
                    <button
                      type="button"
                      onClick={() => remove(line.productId)}
                      aria-label={`Remover ${line.name}`}
                      className="grid size-9 shrink-0 place-items-center rounded-full text-muted hover:bg-danger-soft hover:text-danger"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  )}
                </div>
                <div className="mt-2 flex items-center justify-between gap-3">
                  {compact ? (
                    <span className="text-sm text-muted tabular">Qtd. {line.quantity}</span>
                  ) : (
                    <QuantityStepper
                      size="sm"
                      label={line.name}
                      value={line.quantity}
                      max={max}
                      onChange={(q) => setQuantity(line.productId, q)}
                    />
                  )}
                  <span className="tabular font-display text-lg font-semibold">
                    {formatMoney(line.priceCents * line.quantity)}
                  </span>
                </div>
                {available !== undefined && line.quantity > available && (
                  <p role="alert" className="mt-1.5 text-xs text-danger">
                    {available <= 0 ? "Produto esgotado." : `Só restam ${available} unidades.`}{" "}
                    Ajuste a quantidade.
                  </p>
                )}
              </div>
            </motion.li>
          );
        })}
      </AnimatePresence>
    </ul>
  );
}

export function CartDrawer() {
  const open = useUi((s) => s.cartOpen);
  const setOpen = useUi((s) => s.setCartOpen);
  const count = useCart(selectCount);
  const subtotal = useCart(selectSubtotal);
  const empty = count === 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        side="right"
        title="Seu carrinho"
        description={
          empty ? "Nenhum item por aqui ainda." : `${count} ${pluralize(count, "item", "itens")}`
        }
        className="[&>h2]:px-6 [&>h2]:pt-6 [&>p]:px-6"
      >
        {empty ? (
          <div className="grid flex-1 place-content-center justify-items-center gap-4 px-8 text-center">
            <Illustration name="cart" className="h-40" />
            <p className="font-display text-2xl font-semibold">Seu carrinho está vazio</p>
            <p className="text-muted">Escolha algo que você goste e pague em segundos com PIX.</p>
            <Button asChild onClick={() => setOpen(false)}>
              <Link to="/">Explorar produtos</Link>
            </Button>
          </div>
        ) : (
          <>
            <div className="mt-4 flex-1 overflow-y-auto px-6 py-2">
              <CartLines />
            </div>
            <div className="grid gap-4 border-t border-border bg-surface px-6 py-5">
              <div className="flex items-baseline justify-between">
                <span className="text-muted">Subtotal</span>
                <span className="font-display text-2xl font-semibold">
                  <AnimatedNumber
                    value={subtotal}
                    format={(n) => formatMoney(Math.round(n))}
                    testId="cart-subtotal"
                    duration={0.5}
                  />
                </span>
              </div>
              <Button asChild size="lg" onClick={() => setOpen(false)}>
                <Link to="/checkout">Ir para o pagamento</Link>
              </Button>
              <p className="text-center text-xs text-muted">
                Pagamento por PIX, com confirmação em segundos.
              </p>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
