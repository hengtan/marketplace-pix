import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import { describeFailure, formatWait } from "./copy";

describe("formatWait", () => {
  it("uses the largest friendly unit, rounding up", () => {
    expect(formatWait(1)).toBe("1 segundo");
    expect(formatWait(45)).toBe("45 segundos");
    expect(formatWait(61)).toBe("2 minutos");
    expect(formatWait(3600)).toBe("1 hora");
    expect(formatWait(3601)).toBe("2 horas");
  });
});

describe("describeFailure", () => {
  it("does not offer a retry for a budget limit", () => {
    const f = describeFailure(
      new ApiError("budget exceeded", 429, { scope: "user", retryAfter: 90 }),
    );
    expect(f.retryable).toBe(false);
    expect(f.message).toMatch(/em 2 minutos/);
  });

  it("falls back to tomorrow when the budget limit has no Retry-After", () => {
    const f = describeFailure(new ApiError("budget exceeded", 429, { scope: "user" }));
    expect(f.message).toMatch(/Volte amanhã/);
  });

  it("keeps a plain 429 retryable with the wait", () => {
    const f = describeFailure(new ApiError("slow down", 429, { retryAfter: 12 }));
    expect(f).toMatchObject({ retryable: true, retryAfter: 12 });
    expect(f.message).toMatch(/12 segundos/);
  });

  it("maps 5xx to the unavailable message", () => {
    expect(describeFailure(new ApiError("x", 503, { retryAfter: 30 })).message).toMatch(
      /indisponível agora. Tente de novo em 30 segundos/,
    );
    expect(describeFailure(new ApiError("x", 500)).message).toMatch(/em instantes/);
  });
});
