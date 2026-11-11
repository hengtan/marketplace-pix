import type { ReactNode } from "react";
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
}: {
  message?: string;
  onRetry?: () => void;
  title?: string;
}) {
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
