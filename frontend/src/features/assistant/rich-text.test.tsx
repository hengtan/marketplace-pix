import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithRouter } from "@/test/utils";
import { parseBlocks, RichText } from "./rich-text";
import type { Citation } from "./types";

const citations: Citation[] = [
  { product_id: "a", slug: "fone-bluetooth-nova", name: "Fone Bluetooth Nova ANC", score: 0.4 },
  { product_id: "b", slug: "webcam-clear-4k", name: "Webcam Clear 4K", score: 0.3 },
];

describe("parseBlocks", () => {
  it("separates paragraphs, bullet lists and numbered lists", () => {
    const blocks = parseBlocks("Intro\nsegunda linha\n\n- um\n- dois\n1. a\n2. b\n\nFim");
    expect(blocks.map((b) => b.type)).toEqual(["p", "ul", "ol", "p"]);
    expect(blocks[0]).toEqual({ type: "p", lines: ["Intro", "segunda linha"] });
    expect(blocks[1]).toEqual({ type: "ul", items: ["um", "dois"] });
  });
});

describe("RichText", () => {
  it("renders bold, lists and line breaks", async () => {
    const { container } = await renderWithRouter(
      <RichText text={"Veja **isto**.\nOutra linha\n\n- item 1\n- item 2"} />,
    );
    expect(container.querySelector("strong")?.textContent).toBe("isto");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelectorAll("br")).toHaveLength(1);
  });

  it("turns citation markers into links to the product", async () => {
    await renderWithRouter(
      <RichText text="Melhor opção [1] e alternativa [2]." citations={citations} />,
    );
    const links = await screen.findAllByTestId("citation-chip");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute("href", "/produto/fone-bluetooth-nova");
    expect(links[1]).toHaveAttribute("href", "/produto/webcam-clear-4k");
    expect(links[0]).toHaveAccessibleName("Fonte 1: Fone Bluetooth Nova ANC");
  });

  it("keeps markers without a matching citation as text", async () => {
    const { container } = await renderWithRouter(
      <RichText text="Sem fonte [3]." citations={citations} />,
    );
    expect(container.textContent).toContain("Sem fonte [3].");
    expect(screen.queryByTestId("citation-chip")).toBeNull();
  });

  it("shows hostile input as plain text", async () => {
    const hostile =
      '<img src=x onerror="alert(1)"><script>alert(1)</script>\n- <a href="javascript:alert(1)">x</a>\n**<b>negrito</b>**';
    const { container } = await renderWithRouter(<RichText text={hostile} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
    expect(container.textContent).toContain("<b>negrito</b>");
  });

  it("does not turn markdown links or headings into elements", async () => {
    const { container } = await renderWithRouter(
      <RichText text="# Título [x](http://evil.test)" />,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("h1")).toBeNull();
  });

  it("handles half-received markup while streaming", async () => {
    const { container, rerender } = await renderWithRouter(
      <RichText text="Veja o **Fone Blue" streaming citations={citations} />,
    );
    expect(container.querySelector("strong")?.textContent).toBe("Fone Blue");
    expect(container.textContent).not.toContain("**");
    rerender(<RichText text="Veja [1" streaming citations={citations} />);
    expect(container.textContent).not.toContain("[");
  });
});
