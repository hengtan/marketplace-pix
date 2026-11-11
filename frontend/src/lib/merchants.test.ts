import { describe, expect, it } from "vitest";
import { merchantScope, SEED_MERCHANTS } from "@/lib/merchants";

const trilha = SEED_MERCHANTS.find((m) => m.slug === "trilha-sports") ?? SEED_MERCHANTS[0];
if (!trilha) throw new Error("seed merchants missing");
const all = SEED_MERCHANTS.map((m) => m.id);

describe("merchantScope", () => {
  it("limits a merchant to their own store and hides the admin-only reconciliation", () => {
    const scope = merchantScope({ roles: ["merchant"], merchant_id: trilha.id });
    expect(scope.ids).toEqual([trilha.id]);
    expect(scope.initial).toBe(trilha.id);
    expect(scope.canReconcile).toBe(false);
  });

  it("lets an admin see every store and the reconciliation", () => {
    const scope = merchantScope({ roles: ["admin"], merchant_id: null });
    expect(scope.ids).toEqual(all);
    expect(scope.canReconcile).toBe(true);
    expect(scope.allowed).toBe(true);
  });

  it("falls back to every store when the profile has no store id (mock accounts)", () => {
    const scope = merchantScope({ roles: ["merchant"] });
    expect(scope.ids).toEqual(all);
    expect(scope.canReconcile).toBe(true);
  });

  it("denies customers and guests", () => {
    expect(merchantScope({ roles: ["customer"] }).allowed).toBe(false);
    expect(merchantScope(null).allowed).toBe(false);
  });
});
