import { Link, useLocation } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { ApiError } from "@/api/client";
import { type ArtName, Illustration } from "./illustrations";
import { Reveal } from "./motion/reveal";
import { Button } from "./ui/button";

export function EmptyState({
  title,
  description,
  action,
  art = "search",
}: {
  title: string;
  description: string;
  action?: ReactNode;
  art?: ArtName;
}) {
  return (
    <Reveal className="mx-auto grid max-w-sm justify-items-center gap-3 py-14 text-center">
      <Illustration name={art} />
      <h3 className="text-2xl font-semibold">{title}</h3>
      <p className="text-muted">{description}</p>
      {action && <div className="mt-2">{action}</div>}
    </Reveal>
  );
}

export function ErrorState({
  message,
  onRetry,
  title = "Não foi possível carregar",
  error,
}: {
  message?: string;
  onRetry?: () => void;
  title?: string;
  error?: unknown;
}) {
  const status = error instanceof ApiError ? error.status : undefined;
  if (status === 401 || status === 403) return <AccessState status={status} />;
  return (
    <div
      role="alert"
      className="mx-auto grid max-w-sm justify-items-center gap-3 py-14 text-center"
    >
      <Illustration name="error" />
      <h3 className="text-2xl font-semibold">{title}</h3>
      <p className="text-muted">{message ?? "Algo deu errado. Tente novamente."}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry} className="mt-2">
          Tentar de novo
        </Button>
      )}
    </div>
  );
}

function AccessState({ status }: { status: 401 | 403 }) {
  const href = useLocation({ select: (l) => l.href });
  const expired = status === 401;
  return (
    <div
      role="alert"
      className="mx-auto grid max-w-sm justify-items-center gap-3 py-14 text-center"
    >
      <Illustration name="lost" />
      <h3 className="text-2xl font-semibold">
        {expired ? "Sua sessão expirou" : "Você não tem acesso a esta área"}
      </h3>
      <p className="text-muted">
        {expired
          ? "Entre de novo para continuar de onde parou."
          : "Sua conta não tem permissão para ver este conteúdo. Entre com outra conta ou volte para a loja."}
      </p>
      <div className="mt-2 flex flex-wrap justify-center gap-3">
        <Button asChild>
          <Link to="/entrar" search={{ redirect: href }}>
            {expired ? "Entrar" : "Entrar com outra conta"}
          </Link>
        </Button>
        {!expired && (
          <Button asChild variant="outline">
            <Link to="/">Voltar para a loja</Link>
          </Button>
        )}
      </div>
    </div>
  );
}
