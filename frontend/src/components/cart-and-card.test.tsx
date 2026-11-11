import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { PRODUCTS } from "@/mocks/data";
import { useCart } from "@/store/cart";
import { useUi } from "@/store/ui";
import { renderWithRouter } from "@/test/utils";
import { CartDrawer } from "./cart-drawer";
import { ProductCard } from "./product-card";

const product = PRODUCTS[0];
const noImage = PRODUCTS.find((p) => p.image_url === null);
if (!product || !noImage) throw new Error("seed missing");

describe("ProductCard", () => {
  beforeEach(() => useCart.getState().clear());

  it("shows name, price, rating and adds to the cart", async () => {
    const user = userEvent.setup();
    await renderWithRouter(<ProductCard product={product} available={25} />);
    expect(screen.getByText("R$ 349,90")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Nota 4,7 de 5/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Adicionar Fone Bluetooth Nova ANC/ }));
    expect(useCart.getState().lines[0]?.quantity).toBe(1);
  });

  it("flags low stock and disables the button when sold out", async () => {
    await renderWithRouter(<ProductCard product={product} available={3} />);
    expect(screen.getByText("Últimas 3 unidades")).toBeInTheDocument();
  });

  it("disables adding when sold out", async () => {
    await renderWithRouter(<ProductCard product={product} available={0} />);
    expect(screen.getByText("Esgotado")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /esgotado/ })).toBeDisabled();
  });

  it("renders a graceful fallback instead of a broken image", async () => {
    await renderWithRouter(<ProductCard product={noImage} available={10} />);
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("CartDrawer", () => {
  beforeEach(() => {
    useCart.getState().clear();
    useUi.setState({ cartOpen: true });
  });

  it("shows the empty state", async () => {
    await renderWithRouter(<CartDrawer />);
    expect(await screen.findByText("Seu carrinho está vazio")).toBeInTheDocument();
  });

  it("adjusts quantity and updates the subtotal", async () => {
    const user = userEvent.setup();
    useCart.getState().add(product, 1);
    await renderWithRouter(<CartDrawer />);
    expect(await screen.findByTestId("cart-subtotal")).toHaveTextContent("R$ 349,90");
    await user.click(screen.getByRole("button", { name: /Aumentar quantidade/ }));
    await waitFor(() => expect(screen.getByTestId("cart-subtotal")).toHaveTextContent("R$ 699,80"));
    await user.click(screen.getByRole("button", { name: /Remover/ }));
    expect(await screen.findByText("Seu carrinho está vazio")).toBeInTheDocument();
  });
});
