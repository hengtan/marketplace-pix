export const HERO_TRANSITION = "product-hero";

export function claimTransition(el: HTMLElement | null) {
  if (!el) return;
  for (const other of document.querySelectorAll<HTMLElement>("[data-vt]")) {
    if (other !== el) other.style.viewTransitionName = "";
  }
  el.style.viewTransitionName = HERO_TRANSITION;
}
