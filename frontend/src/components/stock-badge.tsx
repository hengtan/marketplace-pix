import { Badge } from "./ui/misc";

export const LOW_STOCK_THRESHOLD = 5;

export function stockLabel(available: number | undefined): {
  label: string;
  tone: "pix" | "warn" | "danger";
} | null {
  if (available === undefined) return null;
  if (available <= 0) return { label: "Esgotado", tone: "danger" };
  if (available <= LOW_STOCK_THRESHOLD) {
    return {
      label: available === 1 ? "Última unidade" : `Últimas ${available} unidades`,
      tone: "warn",
    };
  }
  return { label: "Em estoque", tone: "pix" };
}

export function StockBadge({ available, hideInStock }: { available: number | undefined; hideInStock?: boolean }) {
  const info = stockLabel(available);
  if (!info || (hideInStock && info.tone === "pix")) return null;
  return <Badge tone={info.tone}>{info.label}</Badge>;
}
