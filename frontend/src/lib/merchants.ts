export interface SeedMerchant {
  id: string;
  slug: string;
  name: string;
}

export const SEED_MERCHANTS: SeedMerchant[] = [
  { id: "1748b018-c69c-53e3-a29d-762cd894d4ff", slug: "aurora-tech", name: "Aurora Tech" },
  { id: "de94438f-b5fc-5639-b59b-778c6e7cba10", slug: "casa-lume", name: "Casa Lume" },
  { id: "435c5a06-d955-566e-9daf-776be4040c6f", slug: "trilha-sports", name: "Trilha Sports" },
];

export const CANCEL_REASONS: Record<string, string> = {
  "out of stock": "Estoque insuficiente. Alguém levou as últimas unidades antes do pagamento.",
  "payment expired": "O PIX expirou antes do pagamento. Nenhum valor foi cobrado.",
};

export function friendlyCancelReason(reason: string | null): string {
  if (!reason) return "O pedido foi cancelado. Nenhum valor foi cobrado.";
  return CANCEL_REASONS[reason] ?? "O pedido foi cancelado. Nenhum valor foi cobrado.";
}
