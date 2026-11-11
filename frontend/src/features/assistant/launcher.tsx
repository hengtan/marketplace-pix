import { m } from "motion/react";
import { useEffect } from "react";
import { useUi } from "@/store/ui";
import { Orb } from "./orb";

export const LAUNCHER_ID = "assistente-botao";

export const isMacLike = () =>
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

export function AssistantLauncher() {
  const open = useUi((s) => s.assistantOpen);
  const setOpen = useUi((s) => s.setAssistantOpen);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key === "/") {
        e.preventDefault();
        const ui = useUi.getState();
        ui.setPaletteOpen(false);
        ui.setAssistantOpen(!ui.assistantOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <m.button
      type="button"
      id={LAUNCHER_ID}
      onClick={() => setOpen(true)}
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-keyshortcuts="Control+/ Meta+/"
      title={`Assistente de compras (${isMacLike() ? "⌘" : "Ctrl"} /)`}
      initial={{ opacity: 0, y: 24, scale: 0.9 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 20, delay: 1.2 }}
      whileHover={{ y: -3 }}
      whileTap={{ scale: 0.95 }}
      className="glass group fixed right-4 bottom-4 z-30 inline-flex h-14 items-center gap-2.5 rounded-full py-0 pr-3 pl-2.5 text-foreground shadow-lift sm:right-6 sm:bottom-6 sm:pr-5"
    >
      <Orb className="size-9" />
      <span className="hidden text-[0.95rem] font-semibold sm:inline">Assistente</span>
      <span className="sr-only sm:hidden">Assistente de compras</span>
      <kbd
        aria-hidden
        className="hidden rounded-sm bg-surface-2 px-1.5 py-0.5 font-mono text-[0.7rem] text-muted sm:inline"
      >
        {isMacLike() ? "⌘/" : "Ctrl /"}
      </kbd>
    </m.button>
  );
}
