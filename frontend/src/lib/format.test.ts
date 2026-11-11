import { describe, expect, it } from "vitest";
import { formatCountdown, formatMoney, formatRating, pluralize, shortId } from "./format";
import { friendlyCancelReason } from "./merchants";

describe("format", () => {
  it("formats cents as BRL", () => {
    expect(formatMoney(34990)).toBe("R$ 349,90");
    expect(formatMoney(5)).toBe("R$ 0,05");
    expect(formatMoney(123456789)).toBe("R$ 1.234.567,89");
  });

  it("formats the countdown as mm:ss and never goes negative", () => {
    expect(formatCountdown(600_000)).toBe("10:00");
    expect(formatCountdown(61_000)).toBe("01:01");
    expect(formatCountdown(999)).toBe("00:01");
    expect(formatCountdown(-5000)).toBe("00:00");
  });

  it("formats ratings with a decimal comma", () => {
    expect(formatRating(4.7)).toBe("4,7");
    expect(formatRating(5)).toBe("5,0");
  });

  it("pluralizes and shortens ids", () => {
    expect(pluralize(1, "item", "itens")).toBe("item");
    expect(pluralize(3, "item", "itens")).toBe("itens");
    expect(shortId("abcdef12-0000")).toBe("ABCDEF12");
  });

  it("maps cancel reasons to friendly copy", () => {
    expect(friendlyCancelReason("out of stock")).toMatch(/Estoque insuficiente/);
    expect(friendlyCancelReason("payment expired")).toMatch(/PIX expirou/);
    expect(friendlyCancelReason(null)).toMatch(/cancelado/);
    expect(friendlyCancelReason("algo novo")).toMatch(/cancelado/);
  });
});
