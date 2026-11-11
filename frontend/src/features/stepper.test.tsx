import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Stepper } from "./stepper";

describe("Stepper", () => {
  it("marks the current step", () => {
    render(<Stepper steps={["Carrinho", "Dados", "PIX"]} current={1} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items[0]).not.toHaveAttribute("aria-current");
  });
});
