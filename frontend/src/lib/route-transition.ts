import { create } from "zustand";
import { prefersReducedMotion } from "@/lib/motion";

const EXIT_FALLBACK_MS = 700;
const RESOLVE_FALLBACK_MS = 4000;

export const useRouteTransition = create<{ leaving: boolean }>(() => ({ leaving: false }));

let release: (() => void) | null = null;
let exited = false;
let exitTimer: ReturnType<typeof setTimeout> | undefined;
let resolveTimer: ReturnType<typeof setTimeout> | undefined;

const isProduct = (path: string) => path.startsWith("/produto/");

export function shouldAnimateExit(from: string | undefined, to: string): boolean {
  if (!from || from === to || prefersReducedMotion()) return false;
  if (isProduct(to) && (from === "/" || isProduct(from))) return false;
  if (isProduct(from) && to === "/") return false;
  return true;
}

export function exitComplete() {
  exited = true;
  clearTimeout(exitTimer);
  release?.();
  release = null;
}

export function endTransition() {
  exited = false;
  clearTimeout(exitTimer);
  clearTimeout(resolveTimer);
  release?.();
  release = null;
  if (useRouteTransition.getState().leaving) useRouteTransition.setState({ leaving: false });
}

export function beginExit(): Promise<void> {
  if (exited) return Promise.resolve();
  return new Promise<void>((resolve) => {
    release = resolve;
    useRouteTransition.setState({ leaving: true });
    exitTimer = setTimeout(exitComplete, EXIT_FALLBACK_MS);
    resolveTimer = setTimeout(endTransition, RESOLVE_FALLBACK_MS);
  });
}
