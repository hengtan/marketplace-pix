import { ArrowUp, Square, SquarePen, X } from "lucide-react";
import { Dialog as D } from "radix-ui";
import { type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { useUi } from "@/store/ui";
import { MAX_MESSAGE_LENGTH, SUGGESTIONS, toolRunningLabel } from "./copy";
import { LAUNCHER_ID } from "./launcher";
import { AssistantMessage, Avatar, HistorySkeleton, UserMessage } from "./message";
import { Orb } from "./orb";
import { useAssistantChat } from "./store";

function announcement(
  last: ReturnType<typeof useAssistantChat.getState>["messages"][number] | undefined,
): string {
  if (last?.role !== "assistant") return "";
  if (last.status === "streaming") {
    const tool = last.toolCalls[last.toolCalls.length - 1];
    return tool && !last.content ? toolRunningLabel(tool.name) : "O assistente está respondendo.";
  }
  if (last.status === "done") return `Resposta do assistente: ${last.content}`;
  if (last.status === "error") return `Erro: ${last.error ?? "não foi possível responder."}`;
  return "Resposta interrompida.";
}

function Composer({ autoFocus }: { autoFocus: boolean }) {
  const send = useAssistantChat((s) => s.send);
  const stop = useAssistantChat((s) => s.stop);
  const streaming = useAssistantChat((s) => s.streaming);
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: resize whenever the text changes
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 150)}px`;
  }, [value]);

  useEffect(() => {
    if (autoFocus) ref.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    if (!streaming && document.activeElement === document.body) ref.current?.focus();
  }, [streaming]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const text = value.trim();
    if (!text || streaming) return;
    setValue("");
    window.dispatchEvent(new Event("assistant:sent"));
    void send(text);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const remaining = MAX_MESSAGE_LENGTH - value.length;

  return (
    <form
      onSubmit={submit}
      className="border-t border-border bg-surface px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
    >
      <div className="flex items-end gap-2 rounded-2xl border border-border-strong/60 bg-background p-1.5 pl-4 transition-colors focus-within:border-primary focus-within:ring-2 focus-within:ring-ring/20">
        <label htmlFor="assistente-mensagem" className="sr-only">
          Sua pergunta para o assistente
        </label>
        <textarea
          id="assistente-mensagem"
          ref={ref}
          rows={1}
          value={value}
          maxLength={MAX_MESSAGE_LENGTH}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Pergunte sobre a loja"
          className="max-h-[150px] min-h-11 flex-1 resize-none self-center bg-transparent py-2.5 text-base outline-none placeholder:text-muted"
        />
        {streaming ? (
          <button
            type="button"
            onClick={stop}
            aria-label="Parar a resposta"
            className="grid size-11 shrink-0 place-items-center rounded-lg bg-foreground text-background transition-transform active:scale-95"
          >
            <Square className="size-4 fill-current" aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            disabled={value.trim().length === 0}
            aria-label="Enviar pergunta"
            className="grid size-11 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground transition-[transform,opacity] active:scale-95 disabled:opacity-40"
          >
            <ArrowUp className="size-5" aria-hidden />
          </button>
        )}
      </div>
      <p className="mt-2 flex justify-between gap-3 px-1 text-xs text-muted">
        <span>O assistente pode errar. Confira preço e estoque na página do produto.</span>
        {remaining <= 100 && (
          <span className={cn("tabular shrink-0", remaining <= 20 && "text-danger")}>
            {remaining}
          </span>
        )}
      </p>
    </form>
  );
}

function EmptyState() {
  const send = useAssistantChat((s) => s.send);
  return (
    <div className="grid h-full content-center justify-items-center gap-3 px-2 py-8 text-center">
      <Orb className="size-20" particles />
      <h3 className="font-display text-2xl font-semibold">Como posso ajudar?</h3>
      <p className="max-w-xs text-muted">
        Pergunto ao catálogo, ao estoque e aos pedidos para responder com dados da loja.
      </p>
      <ul className="mt-3 flex flex-wrap justify-center gap-2" aria-label="Sugestões de perguntas">
        {SUGGESTIONS.map((s) => (
          <li key={s}>
            <button
              type="button"
              onClick={() => {
                window.dispatchEvent(new Event("assistant:sent"));
                void send(s);
              }}
              className="min-h-11 rounded-full border border-border-strong/60 bg-surface px-4 py-2 text-sm font-medium shadow-soft transition-[border-color,color,transform] hover:border-primary hover:text-primary active:scale-[0.97]"
            >
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function AssistantPanel() {
  const open = useUi((s) => s.assistantOpen);
  const setOpen = useUi((s) => s.setAssistantOpen);
  const messages = useAssistantChat((s) => s.messages);
  const streaming = useAssistantChat((s) => s.streaming);
  const loadingHistory = useAssistantChat((s) => s.loadingHistory);
  const hydrate = useAssistantChat((s) => s.hydrate);
  const reset = useAssistantChat((s) => s.reset);
  const retry = useAssistantChat((s) => s.retry);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const last = messages[messages.length - 1];
  const coarse = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;

  useEffect(() => {
    if (open) void hydrate();
  }, [open, hydrate]);

  useEffect(() => {
    const onSent = () => {
      stick.current = true;
    };
    window.addEventListener("assistant:sent", onSent);
    return () => window.removeEventListener("assistant:sent", onSent);
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: follow growth of the last message
  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [messages, loadingHistory, open]);

  const onScroll = () => {
    const el = scroller.current;
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  return (
    <D.Root open={open} onOpenChange={setOpen}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-[oklch(0.12_0.04_275/0.45)] backdrop-blur-sm data-[state=closed]:animate-out data-[state=open]:animate-in data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <D.Content
          data-testid="assistant-panel"
          onOpenAutoFocus={(e) => {
            if (!coarse) e.preventDefault();
          }}
          onCloseAutoFocus={(e) => {
            e.preventDefault();
            document.getElementById(LAUNCHER_ID)?.focus();
          }}
          className="fixed inset-y-0 right-0 z-50 flex h-dvh w-full flex-col bg-[linear-gradient(180deg,var(--surface),color-mix(in_oklab,var(--surface),var(--primary-soft)_35%))] text-foreground shadow-lift outline-none duration-500 ease-out data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:animate-in data-[state=open]:slide-in-from-right sm:max-w-[30rem] sm:rounded-l-3xl sm:border-l sm:border-border"
        >
          <header className="flex items-center gap-3 border-b border-border px-4 py-3">
            <Avatar className="size-10" thinking={streaming} />
            <div className="min-w-0 flex-1">
              <D.Title className="font-display text-lg leading-tight font-semibold whitespace-nowrap">
                Assistente de compras
              </D.Title>
              <D.Description className="truncate text-xs text-muted">
                Responde com dados da loja
              </D.Description>
            </div>
            <button
              type="button"
              onClick={reset}
              disabled={messages.length === 0}
              className="inline-flex h-11 items-center gap-2 rounded-full px-3 text-sm font-medium text-muted transition-colors hover:bg-surface-2 hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
            >
              <SquarePen className="size-4" aria-hidden />
              <span className="sr-only min-[400px]:not-sr-only">Nova conversa</span>
            </button>
            <D.Close
              aria-label="Fechar o assistente"
              className="grid size-11 place-items-center rounded-full text-muted transition-colors hover:bg-surface-2 hover:text-foreground"
            >
              <X className="size-5" aria-hidden />
            </D.Close>
          </header>

          <div
            ref={scroller}
            onScroll={onScroll}
            role="log"
            aria-label="Conversa com o assistente"
            aria-live="off"
            tabIndex={-1}
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5"
          >
            {loadingHistory ? (
              <HistorySkeleton />
            ) : messages.length === 0 ? (
              <EmptyState />
            ) : (
              <div className="grid gap-6">
                {messages.map((m, i) =>
                  m.role === "user" ? (
                    <UserMessage key={m.id} message={m} />
                  ) : (
                    <AssistantMessage
                      key={m.id}
                      message={m}
                      isLast={i === messages.length - 1}
                      onRetry={retry}
                      onNavigate={() => setOpen(false)}
                    />
                  ),
                )}
              </div>
            )}
          </div>

          <div className="sr-only" role="status" aria-live="polite" data-testid="assistant-live">
            {announcement(last)}
          </div>

          <Composer autoFocus={!coarse && open} />
        </D.Content>
      </D.Portal>
    </D.Root>
  );
}
