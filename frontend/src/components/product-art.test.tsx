import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { kindFor } from "./product-art";
import { ProductImage } from "./product-image";

describe("generative product art", () => {
  it("maps slugs to drawn objects and falls back by category", () => {
    expect(kindFor("fone-bluetooth-nova", "tecnologia")).toBe("headphones");
    expect(kindFor("tenis-corrida-vento", "esporte")).toBe("shoe");
    expect(kindFor("algo-novo", "casa")).toBe("vessel");
  });

  it("never loads third-party images", () => {
    const { container } = render(
      <ProductImage
        src="https://images.unsplash.com/photo-1"
        alt=""
        category="tecnologia"
        seed="x"
      />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("keeps first-party images", () => {
    const { container } = render(
      <ProductImage src="/img/a.png" alt="Foto" category="casa" seed="y" />,
    );
    expect(container.querySelector("img")).not.toBeNull();
  });
});
