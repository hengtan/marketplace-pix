export const bootedFromShell =
  typeof document !== "undefined" && document.getElementById("boot-shell")?.hidden === false;

export function afterFirstPaint(): Promise<void> {
  if (!bootedFromShell || typeof PerformanceObserver === "undefined") return Promise.resolve();
  return new Promise((resolve) => {
    const fallback = setTimeout(resolve, 400);
    const observer = new PerformanceObserver((list) => {
      if (list.getEntriesByName("first-contentful-paint").length === 0) return;
      observer.disconnect();
      clearTimeout(fallback);
      resolve();
    });
    observer.observe({ type: "paint", buffered: true });
  });
}
