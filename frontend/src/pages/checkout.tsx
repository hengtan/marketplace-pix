import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Lock, QrCode, ShoppingBag } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import { CartLines } from "@/components/cart-drawer";
import { EmptyState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import { type ContactForm, contactSchema } from "@/features/checkout-schema";
import { usePageTitle } from "@/hooks/utils";
import { formatMoney } from "@/lib/format";
import { selectCount, selectSubtotal, useCart } from "@/store/cart";
import {
  clearIdempotencyKey,
  getContact,
  getCustomerId,
  getIdempotencyKey,
  saveContact,
  signatureOf,
} from "@/store/customer";

export default function CheckoutPage() {
  usePageTitle("Pagamento");
  const navigate = useNavigate();
  const client = useQueryClient();
  const lines = useCart((s) => s.lines);
  const clear = useCart((s) => s.clear);
  const count = useCart(selectCount);
  const subtotal = useCart(selectSubtotal);

  const form = useForm<ContactForm>({
    resolver: zodResolver(contactSchema),
    defaultValues: getContact(),
    mode: "onTouched",
  });
  const { register, handleSubmit, formState } = form;

  const mutation = useMutation({
    mutationFn: async (contact: ContactForm) => {
      const items = lines.map((l) => ({ product_id: l.productId, quantity: l.quantity }));
      const key = getIdempotencyKey(signatureOf(items, contact));
      return api.createOrder(
        {
          customer_id: getCustomerId(),
          customer_name: contact.name.trim(),
          customer_email: contact.email.trim(),
          items,
        },
        key,
      );
    },
    onSuccess: (res, contact) => {
      saveContact({ name: contact.name.trim(), email: contact.email.trim() });
      clearIdempotencyKey();
      clear();
      client.invalidateQueries({ queryKey: ["orders"] });
      client.invalidateQueries({ queryKey: ["notifications"] });
      client.invalidateQueries({ queryKey: ["stock"] });
      navigate({ to: "/pedido/$id", params: { id: res.id } });
    },
    onError: (err) => toast.error(err.message),
  });

  if (count === 0 && !mutation.isSuccess) {
    return (
      <div className="mx-auto max-w-7xl px-4 py-10 sm:px-6">
        <EmptyState
          icon={<ShoppingBag className="size-7" />}
          title="Seu carrinho está vazio"
          description="Adicione produtos para ver o resumo e pagar com PIX."
          action={
            <Button asChild>
              <Link to="/">Explorar produtos</Link>
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-12">
      <h1 className="text-4xl font-bold sm:text-5xl">Finalize com PIX</h1>
      <p className="mt-2 text-muted">Dois dados e pronto. O QR Code aparece na próxima tela.</p>

      <div className="mt-10 grid gap-10 lg:grid-cols-[1fr_26rem] lg:gap-16">
        <form
          onSubmit={handleSubmit((v) => mutation.mutate(v))}
          noValidate
          className="grid content-start gap-6"
          aria-label="Dados de contato"
        >
          <fieldset className="grid gap-5">
            <legend className="mb-1 font-display text-2xl font-semibold">Seus dados</legend>
            <Field label="Nome completo" htmlFor="name" error={formState.errors.name?.message}>
              <Input
                id="name"
                autoComplete="name"
                aria-invalid={Boolean(formState.errors.name)}
                aria-describedby={formState.errors.name ? "name-error" : undefined}
                {...register("name")}
              />
            </Field>
            <Field
              label="E-mail"
              htmlFor="email"
              error={formState.errors.email?.message}
              hint="Enviamos a confirmação do pedido para este endereço."
            >
              <Input
                id="email"
                type="email"
                inputMode="email"
                autoComplete="email"
                aria-invalid={Boolean(formState.errors.email)}
                aria-describedby={formState.errors.email ? "email-error" : "email-hint"}
                {...register("email")}
              />
            </Field>
          </fieldset>

          <Button type="submit" variant="pix" size="lg" disabled={mutation.isPending} className="w-full sm:w-auto sm:min-w-72">
            <QrCode />
            {mutation.isPending ? "Gerando seu PIX..." : `Pagar com PIX, ${formatMoney(subtotal)}`}
          </Button>
          <p className="flex items-center gap-2 text-sm text-muted">
            <Lock className="size-4" /> Seus dados ficam só neste navegador e no pedido.
          </p>
        </form>

        <aside aria-labelledby="resumo" className="h-fit rounded-xl border border-border bg-surface p-6 shadow-soft lg:sticky lg:top-24">
          <h2 id="resumo" className="font-display text-2xl font-semibold">
            Resumo
          </h2>
          <div className="mt-5">
            <CartLines />
          </div>
          <dl className="mt-6 grid gap-2 border-t border-border pt-5">
            <div className="flex justify-between text-muted">
              <dt>Itens</dt>
              <dd className="tabular">{count}</dd>
            </div>
            <div className="flex items-baseline justify-between">
              <dt className="font-medium">Total</dt>
              <dd className="tabular font-display text-3xl font-bold" data-testid="checkout-total">
                {formatMoney(subtotal)}
              </dd>
            </div>
          </dl>
        </aside>
      </div>
    </div>
  );
}
