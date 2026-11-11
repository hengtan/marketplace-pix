import { mkdirSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";

test.setTimeout(120_000);
const OUT = "docs/screenshots";
mkdirSync(OUT, { recursive: true });

async function setTheme(page: Page, theme: "light" | "dark") {
  await page.addInitScript((t) => localStorage.setItem("praca-theme", t), theme);
}

async function shoot(page: Page, name: string, full = false) {
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: full, animations: "disabled" });
}

for (const theme of ["light", "dark"] as const) {
  test(`captures ${theme} desktop`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await setTheme(page, theme);
    await page.goto("/");
    await expect(page.getByTestId("product-card").first()).toBeVisible();
    await shoot(page, `home-${theme}`);
    await shoot(page, `home-full-${theme}`, true);

    await page.goto("/produto/relogio-gps-trail");
    await expect(page.getByRole("heading", { level: 1 })).toContainText("Relógio GPS Trail");
    await shoot(page, `produto-${theme}`);

    await page.getByRole("button", { name: "Adicionar ao carrinho" }).click();
    await page.getByRole("button", { name: /Abrir carrinho/ }).click();
    await expect(page.getByTestId("cart-line")).toHaveCount(1);
    await shoot(page, `carrinho-${theme}`);
    await page.getByRole("link", { name: "Ir para o pagamento" }).click();
    await expect(page.getByRole("heading", { name: "Finalize com PIX" })).toBeVisible();
    await shoot(page, `checkout-${theme}`);

    await page.getByLabel("Nome completo").fill("Maria Souza");
    await page.getByLabel("E-mail").fill("maria@exemplo.com");
    await page.getByRole("button", { name: /Pagar com PIX/ }).click();
    await expect(page.getByTestId("pix-code")).toBeVisible();
    await shoot(page, `pedido-pix-${theme}`);
    await page.getByTestId("simulate-pay").click();
    await expect(page.getByTestId("order-paid")).toBeVisible({ timeout: 10_000 });
    await shoot(page, `pedido-pago-${theme}`);

    await page.goto("/pedidos");
    await expect(page.getByTestId("order-row").first()).toBeVisible();
    await shoot(page, `pedidos-${theme}`);

    await page.goto("/lojista");
    await expect(page.getByText("Saldo a receber")).toBeVisible();
    await page.waitForTimeout(800);
    await shoot(page, `lojista-${theme}`, true);

    await page.goto("/");
    await page.keyboard.press("Control+k");
    await page.getByRole("combobox", { name: /Buscar produtos ou ações/ }).fill("fone");
    await expect(page.getByRole("option", { name: /Fone Bluetooth/ })).toBeVisible();
    await shoot(page, `paleta-${theme}`);
  });
}

test("captures mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setTheme(page, "light");
  await page.goto("/");
  await expect(page.getByTestId("product-card").first()).toBeVisible();
  await shoot(page, "mobile-home");
  await page.goto("/produto/smartwatch-orbit");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shoot(page, "mobile-produto");
  await page.getByRole("button", { name: "Adicionar ao carrinho" }).click();
  await page
    .getByRole("link", { name: /Ir para o pagamento/ })
    .or(page.getByRole("button", { name: /Abrir carrinho/ }))
    .first()
    .click();
  await shoot(page, "mobile-carrinho");
});
