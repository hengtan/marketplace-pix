import { type ComponentType, lazy } from "react";

const FLAG = "praca-chunk-reload";
const CHUNK_ERROR =
  /dynamically imported module|importing a module script failed|Loading chunk|Unable to preload/i;

function reloadPage() {
  window.location.reload();
}

export function loadWithReload<T>(
  load: () => Promise<T>,
  reload: () => void = reloadPage,
): Promise<T> {
  return load().catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    if (!CHUNK_ERROR.test(message)) throw error;
    try {
      if (sessionStorage.getItem(FLAG) === "1") throw error;
      sessionStorage.setItem(FLAG, "1");
    } catch (inner) {
      if (inner === error) throw error;
    }
    reload();
    return new Promise<T>(() => {});
  });
}

export function clearReloadFlag() {
  try {
    sessionStorage.removeItem(FLAG);
  } catch {
    /* storage unavailable */
  }
}

// biome-ignore lint/suspicious/noExplicitAny: React.lazy itself requires ComponentType<any>
export function lazyReload<T extends ComponentType<any>>(load: () => Promise<{ default: T }>) {
  return lazy(() => loadWithReload(load));
}
