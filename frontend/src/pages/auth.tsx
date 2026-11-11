import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { getRouteApi, Link, useNavigate } from "@tanstack/react-router";
import { Eye, EyeOff, LogIn, ShieldCheck, Sparkles, UserPlus, Zap } from "lucide-react";
import { m, useMotionValue, useReducedMotion, useSpring, useTransform } from "motion/react";
import { type ReactNode, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { api } from "@/api/endpoints";
import { Mark } from "@/components/layout/wordmark";
import { Magnetic } from "@/components/motion/magnetic";
import { ProductImage } from "@/components/product-image";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/field";
import {
  type LoginForm,
  loginSchema,
  passwordScore,
  type RegisterForm,
  registerSchema,
  safeRedirect,
} from "@/features/auth-schema";
import { usePageTitle } from "@/hooks/utils";
import { EASE, finePointer } from "@/lib/motion";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { useAuth } from "@/store/auth";

const loginRoute = getRouteApi("/entrar");
const registerRoute = getRouteApi("/cadastro");

const SHOWCASE = [
  {
    slug: "fone-bluetooth-nova",
    category: "tecnologia",
    cls: "left-[6%] top-[14%] w-44 rotate-[-6deg]",
    depth: 18,
  },
  {
    slug: "luminaria-arco-dourado",
    category: "casa",
    cls: "right-[8%] top-[34%] w-52 rotate-[5deg]",
    depth: 34,
  },
  {
    slug: "tenis-corrida-vento",
    category: "esporte",
    cls: "right-[22%] bottom-[6%] w-36 rotate-[4deg]",
    depth: 26,
  },
] as const;

function Showcase() {
  const reduce = useReducedMotion();
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const sx = useSpring(mx, { stiffness: 80, damping: 18 });
  const sy = useSpring(my, { stiffness: 80, damping: 18 });
  useEffect(() => {
    if (reduce || !finePointer()) return;
    const move = (e: PointerEvent) => {
      mx.set(e.clientX / window.innerWidth - 0.5);
      my.set(e.clientY / window.innerHeight - 0.5);
    };
    window.addEventListener("pointermove", move, { passive: true });
    return () => window.removeEventListener("pointermove", move);
  }, [reduce, mx, my]);
  return (
    <div aria-hidden className="absolute inset-0">
      {SHOWCASE.map((s, i) => (
        <ParallaxCard key={s.slug} {...s} sx={sx} sy={sy} index={i} />
      ))}
    </div>
  );
}

function ParallaxCard({
  slug,
  category,
  cls,
  depth,
  sx,
  sy,
  index,
}: (typeof SHOWCASE)[number] & {
  sx: ReturnType<typeof useSpring>;
  sy: ReturnType<typeof useSpring>;
  index: number;
}) {
  const x = useTransform(sx, (v) => v * depth * -2);
  const y = useTransform(sy, (v) => v * depth * -2);
  return (
    <m.div
      className={cn("absolute", cls)}
      style={{ x, y }}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: 0.3 + index * 0.15, duration: 0.9, ease: EASE }}
    >
      <ProductImage
        src={null}
        alt=""
        category={category}
        seed={slug}
        className="rounded-3xl shadow-lift ring-1 ring-white/30"
        float
      />
    </m.div>
  );
}

function AuthFrame({
  title,
  accent,
  subtitle,
  children,
  footer,
}: {
  title: string;
  accent: string;
  subtitle: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <div className="relative isolate overflow-hidden">
      <div className="aurora" aria-hidden>
        <i />
        <i />
        <i />
      </div>
      <div className="mx-auto grid min-h-[calc(100dvh-4.25rem)] max-w-[88rem] lg:grid-cols-[1.05fr_1fr]">
        <aside className="relative hidden lg:block">
          <Showcase />
          <div className="relative z-10 grid h-full content-between p-12">
            <Mark className="size-12" />
            <div className="max-w-md">
              <p className="text-display !text-[clamp(2.6rem,4vw,4.2rem)]">
                Compre.
                <br />
                Pague.
                <br />
                <span className="serif gradient-text pr-2">Pronto.</span>
              </p>
              <ul className="mt-8 grid gap-3 text-muted">
                <li className="flex items-center gap-3">
                  <Zap className="size-5 text-pix-ink" /> PIX confirmado em segundos
                </li>
                <li className="flex items-center gap-3">
                  <ShieldCheck className="size-5 text-pix-ink" /> Estoque reservado no pedido
                </li>
                <li className="flex items-center gap-3">
                  <Sparkles className="size-5 text-pix-ink" /> Assistente que conhece o catálogo
                </li>
              </ul>
            </div>
          </div>
        </aside>
        <section className="grid place-items-center px-4 py-10 sm:px-8">
          <div className="w-full max-w-md">
            <m.div
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: EASE }}
            >
              <h1 className="text-title">
                {title} <span className="serif gradient-text pr-1 font-normal">{accent}</span>
              </h1>
              <p className="mt-3 text-muted">{subtitle}</p>
            </m.div>
            <div className="panel hairline-top mt-8 rounded-3xl p-6 sm:p-8">{children}</div>
            <p className="mt-6 text-center text-sm text-muted">{footer}</p>
            <p className="mt-6 text-center text-xs text-muted">
              Navegar na loja não exige conta. Entre para acessar o painel do lojista e sua conta.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}

function PasswordInput({
  id,
  invalid,
  describedBy,
  autoComplete,
  ...props
}: {
  id: string;
  invalid: boolean;
  describedBy?: string;
  autoComplete: string;
} & React.ComponentProps<"input">) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input
        id={id}
        type={show ? "text" : "password"}
        autoComplete={autoComplete}
        aria-invalid={invalid}
        aria-describedby={describedBy}
        className="pr-12"
        {...props}
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? "Ocultar senha" : "Mostrar senha"}
        aria-pressed={show}
        className="absolute top-1/2 right-1.5 grid size-10 -translate-y-1/2 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-foreground"
      >
        {show ? <EyeOff className="size-[1.1rem]" /> : <Eye className="size-[1.1rem]" />}
      </button>
    </div>
  );
}

function Strength({ value }: { value: string }) {
  const score = passwordScore(value);
  const label = ["Muito curta", "Fraca", "Razoável", "Boa", "Forte"][value ? score : 0];
  return (
    <div aria-live="polite" className="mt-2">
      <div className="flex gap-1.5" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <span key={i} className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
            <m.span
              className={cn(
                "block h-full origin-left rounded-full",
                score <= 1 ? "bg-danger" : score === 2 ? "bg-sun" : "bg-pix",
              )}
              initial={false}
              animate={{ scaleX: value && i < score ? 1 : 0 }}
              transition={{ duration: 0.35, ease: EASE }}
            />
          </span>
        ))}
      </div>
      <p className="mt-1.5 text-xs text-muted">Força da senha: {label}</p>
    </div>
  );
}

function ServerError({ message }: { message: string | null }) {
  const reduce = useReducedMotion();
  if (!message) return null;
  return (
    <m.p
      role="alert"
      key={message}
      initial={reduce ? false : { x: 0 }}
      animate={reduce ? undefined : { x: [0, -8, 8, -5, 5, 0] }}
      transition={{ duration: 0.45 }}
      className="rounded-xl bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      {message}
    </m.p>
  );
}

export function LoginPage() {
  usePageTitle("Entrar");
  const search = loginRoute.useSearch();
  const navigate = useNavigate();
  const setSession = useAuth((s) => s.setSession);
  const { register, handleSubmit, formState } = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    mode: "onTouched",
  });
  const mutation = useMutation({
    mutationFn: api.login,
    onSuccess: (res) => {
      setSession(res);
      toast.success(`Bem-vindo de volta, ${res.user.name.split(" ")[0]}`);
      navigate({ to: safeRedirect(search.redirect) });
    },
  });

  return (
    <AuthFrame
      title="Entre na"
      accent="praça."
      subtitle="Acesse sua conta para ver o painel do lojista e acompanhar seus dados."
      footer={
        <>
          Ainda não tem conta?{" "}
          <Link
            to="/cadastro"
            search={search}
            className="font-semibold text-primary underline-offset-4 hover:underline"
          >
            Criar conta
          </Link>
        </>
      }
    >
      <form
        onSubmit={handleSubmit((v) => mutation.mutate(v))}
        noValidate
        className="grid gap-5"
        aria-label="Entrar"
      >
        <Field label="E-mail" htmlFor="email" error={formState.errors.email?.message}>
          <Input
            id="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            aria-invalid={Boolean(formState.errors.email)}
            aria-describedby={formState.errors.email ? "email-error" : undefined}
            {...register("email")}
          />
        </Field>
        <Field label="Senha" htmlFor="password" error={formState.errors.password?.message}>
          <PasswordInput
            id="password"
            autoComplete="current-password"
            invalid={Boolean(formState.errors.password)}
            describedBy={formState.errors.password ? "password-error" : undefined}
            {...register("password")}
          />
        </Field>
        <ServerError message={mutation.error?.message ?? null} />
        <Magnetic className="w-full">
          <Button type="submit" size="lg" className="w-full" disabled={mutation.isPending}>
            <LogIn /> {mutation.isPending ? "Entrando..." : "Entrar"}
          </Button>
        </Magnetic>
        <p className="rounded-xl bg-surface-2 px-4 py-3 text-xs text-muted">
          Conta de demonstração: <span className="font-mono">lojista@praca.dev</span> com a senha{" "}
          <span className="font-mono">praca1234</span>.
        </p>
      </form>
    </AuthFrame>
  );
}

export function RegisterPage() {
  usePageTitle("Criar conta");
  const search = registerRoute.useSearch();
  const navigate = useNavigate();
  const setSession = useAuth((s) => s.setSession);
  const { register, handleSubmit, formState, watch } = useForm<RegisterForm>({
    resolver: zodResolver(registerSchema),
    mode: "onTouched",
  });
  const password = watch("password") ?? "";
  const mutation = useMutation({
    mutationFn: api.register,
    onSuccess: (res) => {
      setSession(res);
      toast.success("Conta criada", { description: "Você já está dentro da praça." });
      navigate({ to: safeRedirect(search.redirect) });
    },
  });

  return (
    <AuthFrame
      title="Crie sua"
      accent="conta."
      subtitle="Leva menos de um minuto. Sua loja favorita continua aberta para convidados."
      footer={
        <>
          Já tem conta?{" "}
          <Link
            to="/entrar"
            search={search}
            className="font-semibold text-primary underline-offset-4 hover:underline"
          >
            Entrar
          </Link>
        </>
      }
    >
      <form
        onSubmit={handleSubmit((v) => mutation.mutate(v))}
        noValidate
        className="grid gap-5"
        aria-label="Criar conta"
      >
        <Field label="Nome completo" htmlFor="name" error={formState.errors.name?.message}>
          <Input
            id="name"
            autoComplete="name"
            aria-invalid={Boolean(formState.errors.name)}
            aria-describedby={formState.errors.name ? "name-error" : undefined}
            {...register("name")}
          />
        </Field>
        <Field label="E-mail" htmlFor="email" error={formState.errors.email?.message}>
          <Input
            id="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            aria-invalid={Boolean(formState.errors.email)}
            aria-describedby={formState.errors.email ? "email-error" : undefined}
            {...register("email")}
          />
        </Field>
        <div>
          <Field label="Senha" htmlFor="password" error={formState.errors.password?.message}>
            <PasswordInput
              id="password"
              autoComplete="new-password"
              invalid={Boolean(formState.errors.password)}
              describedBy={formState.errors.password ? "password-error" : undefined}
              {...register("password")}
            />
          </Field>
          <Strength value={password} />
        </div>
        <ServerError message={mutation.error?.message ?? null} />
        <Magnetic className="w-full">
          <Button type="submit" size="lg" className="w-full" disabled={mutation.isPending}>
            <UserPlus /> {mutation.isPending ? "Criando conta..." : "Criar conta"}
          </Button>
        </Magnetic>
      </form>
    </AuthFrame>
  );
}
