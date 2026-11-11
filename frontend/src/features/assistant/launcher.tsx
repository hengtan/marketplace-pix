import { Sparkles } from "lucide-react";
import { useEffect } from "react";
import { Kbd } from "@/components/ui/misc";
import { useUi } from "@/store/ui";
import { LAUNCHER_ID } from "./panel";

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
    <button
      type="button"
      id={LAUNCHER_ID}
      onClick={() => setOpen(true)}
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-keyshortcuts="Control+/ Meta+/"
      title={`Assistente de compras (${isMacLike() ? "⌘" : "Ctrl"} /)`}
      className="group fixed right-4 bottom-4 z-30 inline-flex h-14 items-center gap-2.5 rounded-full bg-primary px-4 text-primary-foreground shadow-lift transition-[transform,filter] duration-300 hover:brightness-110 active:scale-95 sm:right-6 sm:bottom-6 sm:pr-5 sm:pl-4"
    >
      <Sparkles
        className="size-5 transition-transform duration-500 group-hover:rotate-12"
        aria-hidden
      />
      <span className="hidden text-[0.95rem] font-semibold sm:inline">Assistente</span>
      <span className="sr-only sm:hidden">Assistente de compras</span>
      <span className="hidden sm:inline" aria-hidden>
        <Kbd>{isMacLike() ? "⌘/" : "Ctrl /"}</Kbd>
      </span>
    </button>
  );
}
