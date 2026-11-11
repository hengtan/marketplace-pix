import { zodResolver } from "@hookform/resolvers/zod";
import { PackagePlus, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { ApiError } from "@/api/client";
import { merchantApi } from "@/api/merchant";
import type { Product } from "@/api/schemas";
import { ProductImage } from "@/components/product-image";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/field";
import { Badge, Skeleton } from "@/components/ui/misc";
import { useCreateProduct, useDeactivateProduct, useUpdateProduct } from "@/hooks/merchant";
import { useCategories } from "@/hooks/queries";
import { formatMoney } from "@/lib/format";
import { writeErrorMessage } from "@/lib/merchant-errors";
import { normalize, parseStockInput } from "@/lib/merchant-metrics";
import { EASE } from "@/lib/motion";
import { toast } from "@/lib/toast";
import { useMerchant, useMerchantNav } from "./context";
import { useStockRows } from "./data";
import {
  formDefaults,
  type ProductForm,
  productFormSchema,
  toNewProduct,
  toPatch,
} from "./product-schema";
import { Card } from "./ui";

function ProductDialog({
  product,
  open,
  onClose,
}: {
  product: Product | null;
  open: boolean;
  onClose: () => void;
}) {
  const { merchantId, isAdmin } = useMerchant();
  const categories = useCategories();
  const create = useCreateProduct(merchantId);
  const update = useUpdateProduct(merchantId);
  const [formError, setFormError] = useState<string | null>(null);
  const editing = product !== null;
  const form = useForm<ProductForm>({
    resolver: zodResolver(productFormSchema),
    defaultValues: formDefaults(product ?? undefined),
  });
  const { register, handleSubmit, formState, reset, setError } = form;
  const { errors } = formState;

  useEffect(() => {
    if (open) {
      reset(formDefaults(product ?? undefined));
      setFormError(null);
    }
  }, [open, product, reset]);

  const submit = handleSubmit(async (values) => {
    setFormError(null);
    try {
      if (product) {
        const patch = toPatch(values, product);
        if (Object.keys(patch).length === 0) return onClose();
        await update.mutateAsync({ id: product.id, patch });
        void toast.success("Produto atualizado", { description: values.name.trim() });
      } else {
        const created = await create.mutateAsync(
          toNewProduct(values, isAdmin ? merchantId : undefined),
        );
        const stock = parseStockInput(values.stock.trim() === "" ? "0" : values.stock);
        if (stock.ok && stock.value > 0) {
          await merchantApi.setStock(created.id, stock.value).catch(() => {
            void toast.error("Produto criado, estoque não definido", {
              description: "Defina as unidades na aba Estoque.",
            });
          });
        }
        void toast.success("Produto criado", {
          description: `${created.name} já está na vitrine.`,
        });
      }
      onClose();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setError("name", { message: writeErrorMessage(error, "catálogo") });
        return;
      }
      setFormError(writeErrorMessage(error, "catálogo"));
    }
  });

  const pending = create.isPending || update.isPending;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        title={editing ? "Editar produto" : "Novo produto"}
        description={
          editing ? "Altere nome, preço e detalhes." : "Preencha os dados para colocar na vitrine."
        }
        className="max-h-[92dvh] max-w-xl overflow-y-auto p-6"
      >
        <form onSubmit={submit} noValidate className="mt-5 grid gap-4">
          <Field label="Nome" htmlFor="pf-name" error={errors.name?.message}>
            <Input
              id="pf-name"
              autoComplete="off"
              aria-invalid={errors.name ? true : undefined}
              aria-describedby={errors.name ? "pf-name-error" : undefined}
              {...register("name")}
            />
          </Field>
          <Field label="Descrição" htmlFor="pf-description" error={errors.description?.message}>
            <textarea
              id="pf-description"
              rows={3}
              aria-invalid={errors.description ? true : undefined}
              aria-describedby={errors.description ? "pf-description-error" : undefined}
              className="w-full rounded-xl border border-border-strong/60 bg-surface px-4 py-3 text-base text-foreground placeholder:text-muted/80 transition-colors hover:border-muted focus-visible:border-primary aria-[invalid=true]:border-danger"
              {...register("description")}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Preço (R$)" htmlFor="pf-price" error={errors.price?.message}>
              <Input
                id="pf-price"
                inputMode="decimal"
                placeholder="49,90"
                aria-invalid={errors.price ? true : undefined}
                aria-describedby={errors.price ? "pf-price-error" : undefined}
                {...register("price")}
              />
            </Field>
            <Field label="Categoria" htmlFor="pf-category" error={errors.category?.message}>
              <Select
                id="pf-category"
                className="h-12 w-full"
                aria-invalid={errors.category ? true : undefined}
                aria-describedby={errors.category ? "pf-category-error" : undefined}
                {...register("category")}
              >
                <option value="">Escolha...</option>
                {(categories.data ?? []).map((c) => (
                  <option key={c.slug} value={c.slug}>
                    {c.label}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="Etiquetas"
              htmlFor="pf-tags"
              hint="Separe por vírgula. Ajudam na busca."
              error={errors.tags?.message}
            >
              <Input id="pf-tags" autoComplete="off" {...register("tags")} />
            </Field>
            {!editing && (
              <Field
                label="Estoque inicial"
                htmlFor="pf-stock"
                hint="Unidades disponíveis para venda."
                error={errors.stock?.message}
              >
                <Input id="pf-stock" inputMode="numeric" {...register("stock")} />
              </Field>
            )}
          </div>
          {formError && (
            <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">
              {formError}
            </p>
          )}
          <div className="mt-2 flex flex-wrap justify-end gap-3">
            <Button variant="ghost" onClick={onClose}>
              Cancelar
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? "Salvando..." : editing ? "Salvar alterações" : "Criar produto"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeactivateDialog({ product, onClose }: { product: Product | null; onClose: () => void }) {
  const { merchantId } = useMerchant();
  const deactivate = useDeactivateProduct(merchantId);
  return (
    <Dialog open={product !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        title="Desativar produto?"
        description="O produto sai da vitrine e não recebe novos pedidos."
        className="max-w-md p-6"
      >
        <p className="mt-4 text-sm">
          <strong>{product?.name}</strong> some da vitrine, das buscas e do carrinho de quem ainda
          não pagou. Pedidos já feitos continuam valendo. A API não tem reativação: para vender de
          novo será preciso cadastrar outro produto.
        </p>
        <div className="mt-6 flex flex-wrap justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            Manter produto
          </Button>
          <Button
            variant="danger"
            disabled={deactivate.isPending}
            onClick={() => {
              if (!product) return;
              deactivate.mutate(product.id, {
                onSuccess: () =>
                  void toast.success("Produto desativado", { description: product.name }),
              });
              onClose();
            }}
          >
            Desativar
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function Products() {
  const { creatingProduct } = useMerchant();
  const nav = useMerchantNav();
  const { products, rows } = useStockRows();
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<Product | null>(null);
  const [removing, setRemoving] = useState<Product | null>(null);

  const stockBy = useMemo(
    () => new Map((rows ?? []).map((r) => [r.productId, r.available])),
    [rows],
  );
  const list = useMemo(() => {
    const q = normalize(text.trim());
    return (products.data ?? []).filter(
      (p) => !q || normalize(`${p.name} ${p.tags.join(" ")}`).includes(q),
    );
  }, [products.data, text]);

  return (
    <Card aria-labelledby="produtos-titulo">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="produtos-titulo" className="font-display text-xl font-semibold">
            Produtos
          </h2>
          <p className="mt-1 text-sm text-muted">
            Edite nome e preço, ou cadastre um produto novo.
          </p>
        </div>
        <Button onClick={nav.newProduct}>
          <Plus aria-hidden /> Novo produto
        </Button>
      </div>

      <div className="relative mt-5">
        <Search
          className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted"
          aria-hidden
        />
        <Input
          type="search"
          data-merchant-search
          aria-label="Buscar produto no catálogo"
          placeholder="Buscar produto"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="h-11 pl-10"
        />
      </div>

      <div className="mt-5">
        {products.isError ? (
          <ErrorState
            error={products.error}
            onRetry={() => products.refetch()}
            title="Não foi possível carregar os produtos"
          />
        ) : products.isPending ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy>
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-44 rounded-2xl" />
            ))}
          </div>
        ) : (products.data ?? []).length === 0 ? (
          <EmptyState
            art="cart"
            title="Sua vitrine ainda está vazia"
            description="Cadastre o primeiro produto e acompanhe vendas e estoque por aqui."
            action={
              <Button onClick={nav.newProduct}>
                <PackagePlus aria-hidden /> Cadastrar produto
              </Button>
            }
          />
        ) : list.length === 0 ? (
          <EmptyState
            art="search"
            title="Nenhum produto encontrado"
            description="Tente outro nome ou etiqueta."
          />
        ) : (
          <ul
            className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
            aria-label="Produtos da loja"
          >
            <AnimatePresence initial>
              {list.map((p, i) => {
                const available = stockBy.get(p.id);
                return (
                  <m.li
                    key={p.id}
                    layout="position"
                    data-testid="merchant-product"
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.96 }}
                    transition={{ duration: 0.45, delay: Math.min(i, 8) * 0.04, ease: EASE }}
                    className="group flex gap-4 rounded-2xl border border-border bg-surface p-4 transition-[transform,box-shadow] duration-300 hover:-translate-y-0.5 hover:shadow-lift"
                  >
                    <ProductImage
                      src={p.image_url}
                      alt=""
                      category={p.category}
                      seed={p.slug}
                      size={160}
                      className="size-20 shrink-0 rounded-xl"
                    />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <h3 className="truncate font-semibold">{p.name}</h3>
                      <p className="tabular mt-0.5 font-display text-lg font-bold">
                        {formatMoney(p.price_cents)}
                      </p>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                        <Badge tone="primary">{p.category}</Badge>
                        {available !== undefined && (
                          <span className="tabular text-muted">{available} em estoque</span>
                        )}
                      </div>
                      <div className="mt-3 flex gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setEditing(p)}
                          aria-label={`Editar ${p.name}`}
                        >
                          <Pencil aria-hidden /> Editar
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setRemoving(p)}
                          aria-label={`Desativar ${p.name}`}
                          className="text-danger hover:bg-danger-soft"
                        >
                          <Trash2 aria-hidden /> Desativar
                        </Button>
                      </div>
                    </div>
                  </m.li>
                );
              })}
            </AnimatePresence>
          </ul>
        )}
      </div>

      <ProductDialog
        key={editing?.id ?? "new"}
        product={editing}
        open={creatingProduct || editing !== null}
        onClose={() => {
          setEditing(null);
          if (creatingProduct) nav.closeNewProduct();
        }}
      />
      <DeactivateDialog product={removing} onClose={() => setRemoving(null)} />
    </Card>
  );
}
