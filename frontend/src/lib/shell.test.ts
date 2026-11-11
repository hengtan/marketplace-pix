import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve(import.meta.dirname, "../..");
const html = readFileSync(path.join(root, "index.html"), "utf8");
const hero = readFileSync(path.join(root, "src/features/hero.tsx"), "utf8");

describe("static shell", () => {
  it("repeats the hero copy so the swap to React is invisible", () => {
    for (const text of [
      "PIX com confirmação em tempo real",
      "Produtos de lojistas independentes, estoque conferido em tempo real e pagamento por PIX que confirma na hora.",
    ]) {
      expect(hero).toContain(text.replace(/ que confirma na hora\.$/, ""));
      expect(html).toContain(text);
    }
    for (const word of ["Compre", "hoje.", "Pague", "em", "segundos."]) {
      expect(html).toContain(word);
    }
  });

  it("is hidden unless the route is the home", () => {
    expect(html).toContain('id="boot-shell"');
    expect(html).toMatch(/hidden/);
    expect(html).toContain('location.pathname === "/"');
  });
});
