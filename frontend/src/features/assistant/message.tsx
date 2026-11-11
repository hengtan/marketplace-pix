import { AlertCircle, Check, Info, Loader2, RotateCcw } from "lucide-react";
import { m } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EASE } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { CitedProducts } from "./cited-products";
import { formatWait, toolDoneLabel, toolRunningLabel } from "./copy";
import { Orb } from "./orb";
import { RichText } from "./rich-text";
import type { ChatMessage } from "./store";
import { Trace } from "./trace";

export function Avatar({ className, thinking }: { className?: string; thinking?: boolean }) {
  return <Orb className={className} thinking={thinking} />;
}

function RetryButton({ retryAfter, onRetry }: { retryAfter?: number; onRetry: () => void }) {
  const until = useRef(Date.now() + (retryAfter ?? 0) * 1000);
  const [remaining, setRemaining] = useState(retryAfter ?? 0);

  useEffect(() => {
    if (!retryAfter) return;
    const id = setInterval(() => {
      const left = Math.ceil((until.current - Date.now()) / 1000);
      setRemaining(Math.max(0, left));
      if (left <= 0) clearInterval(id);
    }, 1000);
    return () => clearInterval(id);
  }, [retryAfter]);

  return (
    <Button
      size="sm"
      variant="outline"
      onClick={onRetry}
      disabled={remaining > 0}
      className="bg-surface"
    >
      <RotateCcw aria-hidden />
      {remaining > 0 ? `Tentar de novo em ${formatWait(remaining)}` : "Tentar de novo"}
    </Button>
  );
}

export function TypingDots({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-muted" data-testid="typing">
      <span className="flex gap-1" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="size-1.5 animate-pulse rounded-full bg-primary"
            style={{ animationDelay: `${i * 180}ms` }}
          />
        ))}
      </span>
      {label}
    </span>
  );
}

export function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <m.div
      className="flex justify-end"
      data-testid="user-message"
      initial={{ opacity: 0, y: 14, scale: 0.96 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.45, ease: EASE }}
    >
      <p className="max-w-[85%] rounded-2xl rounded-br-md bg-[linear-gradient(160deg,color-mix(in_oklab,var(--primary),white_12%),var(--primary))] px-4 py-2.5 text-[0.95rem] leading-relaxed break-words whitespace-pre-wrap text-primary-foreground shadow-soft">
        {message.content}
      </p>
    </m.div>
  );
}

export function AssistantMessage({
  message,
  isLast,
  onRetry,
  onNavigate,
}: {
  message: ChatMessage;
  isLast: boolean;
  onRetry: () => void;
  onNavigate: () => void;
}) {
  const streaming = message.status === "streaming";
  const hasText = message.content.length > 0;
  const lastTool = message.toolCalls[message.toolCalls.length - 1];
  const showSteps = message.toolCalls.length > 0 && (hasText || !streaming);

  return (
    <m.div
      className="flex gap-3"
      data-testid="assistant-message"
      data-status={message.status}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: EASE }}
    >
      <Avatar className="mt-0.5" thinking={streaming && !hasText} />
      <div className="min-w-0 flex-1 text-[0.95rem] leading-relaxed">
        {streaming && !hasText && (
          <TypingDots label={lastTool ? toolRunningLabel(lastTool.name) : "Pensando..."} />
        )}

        {showSteps && (
          <ul className="mb-2 flex flex-wrap gap-1.5" aria-label="Etapas">
            {message.toolCalls.map((call, i) => (
              <li
                key={i}
                className="inline-flex items-center gap-1 rounded-full bg-pix-soft px-2.5 py-1 text-xs font-medium text-pix-ink"
              >
                <Check className="size-3" aria-hidden />
                {toolDoneLabel(call.name)}
              </li>
            ))}
          </ul>
        )}

        {hasText && (
          <RichText
            text={message.content}
            citations={message.citations}
            onNavigate={onNavigate}
            streaming={streaming}
          />
        )}

        {message.notice && message.status !== "error" && (
          <p
            role="status"
            data-testid="degraded-notice"
            className="mt-3 flex items-start gap-2 rounded-lg bg-warn-soft px-3.5 py-2.5 text-sm text-warn"
          >
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>{message.notice}</span>
          </p>
        )}

        {message.status === "stopped" && (
          <p className="mt-2 text-sm text-muted">
            {hasText ? "Resposta interrompida." : "Você interrompeu a resposta."}
          </p>
        )}

        {(message.status === "error" || message.status === "stopped") && isLast && (
          <div
            role={message.status === "error" ? "alert" : undefined}
            className={cn(
              "mt-3 flex flex-wrap items-center gap-3 rounded-lg px-3.5 py-3 text-sm",
              message.status === "error" ? "bg-danger-soft text-danger" : "bg-surface-2",
            )}
          >
            {message.status === "error" && (
              <p className="flex min-w-0 flex-1 basis-48 items-start gap-2">
                <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span>{message.error}</span>
              </p>
            )}
            {(message.status === "stopped" || message.retryable !== false) && (
              <RetryButton retryAfter={message.retryAfter} onRetry={onRetry} />
            )}
          </div>
        )}

        {message.status === "done" && (
          <>
            <CitedProducts citations={message.citations} onNavigate={onNavigate} />
            <Trace
              toolCalls={message.toolCalls}
              retrieved={message.retrieved}
              latencyMs={message.latencyMs}
            />
          </>
        )}
      </div>
    </m.div>
  );
}

export function HistorySkeleton() {
  return (
    <div className="grid gap-5" aria-hidden>
      <div className="ml-auto skeleton h-10 w-2/3 rounded-lg" />
      <div className="flex gap-3">
        <div className="skeleton size-8 rounded-full" />
        <div className="grid flex-1 gap-2">
          <div className="skeleton h-4 w-full rounded" />
          <div className="skeleton h-4 w-4/5 rounded" />
          <div className="skeleton h-4 w-3/5 rounded" />
        </div>
      </div>
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("animate-spin", className)} aria-hidden />;
}
