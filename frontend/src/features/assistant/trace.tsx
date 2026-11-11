import { Check, ChevronDown, FileText, Gauge, Wrench } from "lucide-react";
import { useId, useState } from "react";
import { cn } from "@/lib/utils";
import { toolTitle } from "./copy";
import type { Retrieved, ToolCall } from "./types";

const num = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatLatency(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1).replace(".", ",")} s` : `${Math.round(ms)} ms`;
}

function formatArg(value: unknown): string {
  const text = typeof value === "string" ? `"${value}"` : JSON.stringify(value);
  return text.length > 90 ? `${text.slice(0, 89)}…` : text;
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

interface TraceProps {
  toolCalls: ToolCall[];
  retrieved: Retrieved[];
  latencyMs: number | null;
}

function Step({
  icon,
  title,
  aside,
  last,
  children,
}: {
  icon: React.ReactNode;
  title: React.ReactNode;
  aside?: React.ReactNode;
  last?: boolean;
  children?: React.ReactNode;
}) {
  return (
    <li className="relative grid grid-cols-[1.5rem_1fr] gap-3 pb-4 last:pb-0">
      {!last && (
        <span aria-hidden className="absolute top-6 bottom-0 left-[0.7rem] w-px bg-border" />
      )}
      <span className="z-10 grid size-6 place-items-center rounded-full border border-border bg-surface text-primary [&_svg]:size-3.5">
        {icon}
      </span>
      <div className="min-w-0">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-sm font-semibold">{title}</p>
          {aside}
        </div>
        {children}
      </div>
    </li>
  );
}

export function Trace({ toolCalls, retrieved, latencyMs }: TraceProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  if (toolCalls.length === 0 && retrieved.length === 0 && latencyMs === null) return null;

  const parts = [
    plural(toolCalls.length, "ferramenta", "ferramentas"),
    ...(retrieved.length ? [plural(retrieved.length, "trecho", "trechos")] : []),
    ...(latencyMs !== null ? [formatLatency(latencyMs)] : []),
  ];

  return (
    <div className="mt-3 rounded-lg border border-border bg-surface-2/50">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-11 w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm"
      >
        <span className="font-medium">Como cheguei nessa resposta</span>
        <span className="tabular ml-auto hidden truncate text-xs text-muted min-[420px]:inline">
          {parts.join(" · ")}
        </span>
        <ChevronDown
          aria-hidden
          className={cn(
            "size-4 shrink-0 text-muted transition-transform duration-300",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div id={id} className="animate-in fade-in-0 border-t border-border px-3 py-4 duration-300">
          <ol className="grid" data-testid="trace">
            {toolCalls.map((call, i) => (
              <Step
                key={i}
                icon={<Wrench aria-hidden />}
                title={
                  <>
                    {toolTitle(call.name)}{" "}
                    <code className="ml-1 rounded-sm bg-surface-2 px-1.5 py-0.5 font-mono text-[0.7rem] font-normal text-muted">
                      {call.name}
                    </code>
                  </>
                }
                aside={
                  <span className="tabular shrink-0 text-xs text-muted">
                    {formatLatency(call.duration_ms)}
                  </span>
                }
              >
                {Object.keys(call.arguments).length > 0 && (
                  <dl className="mt-1.5 grid gap-1">
                    {Object.entries(call.arguments).map(([key, value]) => (
                      <div key={key} className="flex flex-wrap gap-x-2 text-xs">
                        <dt className="font-mono text-muted">{key}</dt>
                        <dd className="min-w-0 font-mono break-words">{formatArg(value)}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {call.result_summary && (
                  <p className="mt-1.5 text-sm leading-snug text-muted">{call.result_summary}</p>
                )}
              </Step>
            ))}

            {retrieved.length > 0 && (
              <Step
                icon={<FileText aria-hidden />}
                title="Trechos recuperados"
                last={latencyMs === null}
              >
                <ul className="mt-2 grid gap-2">
                  {retrieved.map((r) => (
                    <li
                      key={r.chunk_id}
                      className="rounded-md border border-border bg-surface px-3 py-2"
                      data-testid="retrieved-chunk"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <p className="min-w-0 truncate text-sm font-medium">{r.name}</p>
                        <span className="tabular shrink-0 text-xs font-semibold text-primary">
                          <span className="sr-only">Pontuação </span>
                          {num.format(r.score)}
                        </span>
                      </div>
                      <div
                        aria-hidden
                        className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-2"
                      >
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{ width: `${Math.min(100, Math.max(4, r.score * 100))}%` }}
                        />
                      </div>
                      <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-muted">
                        {r.content}
                      </p>
                    </li>
                  ))}
                </ul>
              </Step>
            )}

            {latencyMs !== null && (
              <Step
                last
                icon={<Check aria-hidden />}
                title="Resposta montada"
                aside={
                  <span className="tabular shrink-0 text-xs text-muted">
                    {formatLatency(latencyMs)}
                  </span>
                }
              >
                <p className="mt-1 flex items-center gap-1.5 text-sm text-muted">
                  <Gauge className="size-3.5" aria-hidden />
                  Tempo total, da pergunta ao fim do texto.
                </p>
              </Step>
            )}
          </ol>
        </div>
      )}
    </div>
  );
}
