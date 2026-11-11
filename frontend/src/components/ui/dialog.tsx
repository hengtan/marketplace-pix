import { X } from "lucide-react";
import { Dialog as D } from "radix-ui";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

export const Dialog = D.Root;
export const DialogTrigger = D.Trigger;
export const DialogClose = D.Close;

interface ContentProps extends ComponentProps<typeof D.Content> {
  title: string;
  description?: string;
  side?: "center" | "right" | "top";
  hideTitle?: boolean;
  children: ReactNode;
}

export function DialogContent({
  title,
  description,
  side = "center",
  hideTitle,
  className,
  children,
  ...props
}: ContentProps) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-[oklch(0.15_0.04_268/0.55)] backdrop-blur-[2px] data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
      <D.Content
        className={cn(
          "fixed z-50 flex flex-col bg-surface text-foreground shadow-lift outline-none duration-300 data-[state=closed]:animate-out data-[state=open]:animate-in",
          side === "center" &&
            "top-1/2 left-1/2 max-h-[90dvh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-lg data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95",
          side === "right" &&
            "inset-y-0 right-0 h-dvh w-full max-w-md data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right sm:rounded-l-xl",
          side === "top" &&
            "top-[10dvh] left-1/2 w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-lg data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-4",
          className,
        )}
        {...props}
      >
        <D.Title className={cn("font-display text-xl font-semibold", hideTitle && "sr-only")}>
          {title}
        </D.Title>
        <D.Description className={description && !hideTitle ? "text-sm text-muted" : "sr-only"}>
          {description ?? title}
        </D.Description>
        {children}
        {side !== "top" && (
          <D.Close
            aria-label="Fechar"
            className="absolute top-3 right-3 grid size-11 place-items-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
          >
            <X className="size-5" />
          </D.Close>
        )}
      </D.Content>
    </D.Portal>
  );
}
