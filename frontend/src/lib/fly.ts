import { animate } from "motion";
import { prefersReducedMotion } from "./motion";

export const CART_BUTTON_ID = "carrinho-botao";

export function flyToCart(source: Element | null | undefined, onLand?: () => void) {
  const target = document.getElementById(CART_BUTTON_ID);
  if (!source || !target || prefersReducedMotion()) {
    onLand?.();
    return;
  }
  const from = source.getBoundingClientRect();
  const to = target.getBoundingClientRect();
  if (from.width === 0) {
    onLand?.();
    return;
  }
  const ghost = source.cloneNode(true) as HTMLElement;
  ghost.removeAttribute("id");
  ghost.setAttribute("aria-hidden", "true");
  Object.assign(ghost.style, {
    position: "fixed",
    left: `${from.left}px`,
    top: `${from.top}px`,
    width: `${from.width}px`,
    height: `${from.height}px`,
    margin: "0",
    zIndex: "95",
    pointerEvents: "none",
    borderRadius: "18px",
    overflow: "hidden",
    willChange: "transform, opacity",
    boxShadow: "0 20px 40px -12px oklch(0.3 0.1 270 / 0.45)",
    viewTransitionName: "none",
    transformOrigin: "center",
  });
  document.body.appendChild(ghost);
  const dx = to.left + to.width / 2 - (from.left + from.width / 2);
  const dy = to.top + to.height / 2 - (from.top + from.height / 2);
  const scale = Math.max(0.12, 36 / from.width);
  const dur = 0.85;
  const x = animate(ghost, { x: dx }, { duration: dur, ease: [0.45, 0, 0.25, 1] });
  animate(ghost, { y: dy }, { duration: dur, ease: [0.6, -0.5, 0.7, 0.9] });
  animate(ghost, { scale, rotate: 18 }, { duration: dur, ease: [0.5, 0, 0.5, 1] });
  animate(ghost, { opacity: [1, 1, 0.15] }, { duration: dur, times: [0, 0.7, 1] });
  x.then(() => {
    ghost.remove();
    onLand?.();
  });
}
