import type { Product } from "@/api/schemas";

const TTL_MS = 120_000;

interface Stamped<T> {
  value: T;
  at: number;
}

const removed = new Map<string, number>();
const patched = new Map<string, Stamped<Product>>();
const created = new Map<string, Stamped<Product>>();

export function rememberRemoved(id: string, now = Date.now()) {
  removed.set(id, now);
  patched.delete(id);
  created.delete(id);
}

export function forgetRemoved(id: string) {
  removed.delete(id);
}

export function rememberPatched(product: Product, now = Date.now()) {
  patched.set(product.id, { value: product, at: now });
}

export function rememberCreated(product: Product, now = Date.now()) {
  created.set(product.id, { value: product, at: now });
}

export function forgetRecentWrites() {
  removed.clear();
  patched.clear();
  created.clear();
}

function purge(now: number) {
  for (const [id, at] of removed) if (now - at > TTL_MS) removed.delete(id);
  for (const map of [patched, created])
    for (const [id, s] of map) if (now - s.at > TTL_MS) map.delete(id);
}

export function applyRecentWrites(
  list: Product[],
  merchantId: string,
  now = Date.now(),
): Product[] {
  purge(now);
  const present = new Set(list.map((p) => p.id));
  const merged = list.filter((p) => !removed.has(p.id)).map((p) => patched.get(p.id)?.value ?? p);
  const extra = [...created.values()]
    .map((s) => s.value)
    .filter((p) => p.merchant.id === merchantId && !present.has(p.id) && !removed.has(p.id))
    .map((p) => patched.get(p.id)?.value ?? p);
  return [...extra, ...merged];
}
