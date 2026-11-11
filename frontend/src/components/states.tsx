import { PackageSearch, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "./ui/button";

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="mx-auto grid max-w-sm justify-items-center gap-3 py-16 text-center">
      <div className="grid size-16 place-items-center rounded-full bg-primary-soft text-primary">
        {icon ?? <PackageSearch className="size-7" />}
      </div>
      <h3 className="text-xl font-semibold">{title}</h3>
      <p className="text-muted">{description}</p>
      {action}
    </div>
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
      className="mx-auto grid max-w-sm justify-items-center gap-3 py-16 text-center"
    >
      <div className="grid size-16 place-items-center rounded-full bg-danger-soft text-danger">
        <TriangleAlert className="size-7" />
      </div>
      <h3 className="text-xl font-semibold">{title}</h3>
      <p className="text-muted">{message ?? "Algo deu errado. Tente novamente."}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry}>
          Tentar de novo
        </Button>
      )}
    </div>
  );
}
