import { mkdirSync } from "node:fs";
import { expect, type Page, test } from "@playwright/test";

test.setTimeout(180_000);
const OUT = "docs/screenshots";
mkdirSync(OUT, { recursive: true });

async function theme(page: Page, t: "light" | "dark") {
  await page.addInitScript((v) => localStorage.setItem("praca-theme", v), t);
}

async function shoot(page: Page, name: string) {
  await page.waitForTimeout(1800);
  await page.screenshot({ path: `${OUT}/${name}.png`, animations: "disabled" });
}

async function signIn(page: Page, redirect: string) {
  await page.goto(`/entrar?redirect=${encodeURIComponent(redirect)}`);
  await page.getByLabel("E-mail").fill("lojista@praca.dev");
  await page.getByLabel("Senha", { exact: true }).fill("praca1234");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
}

test("desktop captures", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await theme(page, "light");
  await page.goto("/");
  await expect(page.getByTestId("product-card").first()).toBeVisible();
  await shoot(page, "01-home-claro");

  await page.goto("/entrar");
  await shoot(page, "02-entrar-claro");

  await page.goto("/produto/fone-bluetooth-nova");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Fone Bluetooth");
  await shoot(page, "03-produto-claro");

  await page.getByRole("button", { name: "Adicionar ao carrinho" }).click();
  await page.getByRole("button", { name: /Abrir carrinho/ }).click();
  await page.getByRole("link", { name: "Ir para o pagamento" }).click();
  await page.getByLabel("Nome completo").fill("Maria Souza");
  await page.getByLabel("E-mail").fill("maria@exemplo.com");
  await page.getByRole("button", { name: /Pagar com PIX/ }).click();
  await expect(page.getByTestId("pix-code")).toBeVisible();
  await shoot(page, "04-pix-claro");
});

test("dark captures", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await theme(page, "dark");
  await page.goto("/");
  await expect(page.getByTestId("product-card").first()).toBeVisible();
  await shoot(page, "05-home-escuro");

  await page.setViewportSize({ width: 1280, height: 1160 });
  await signIn(page, "/lojista");
  await expect(page.getByText("Saldo a receber")).toBeVisible();
  await page.addStyleTag({ content: "*{--noise-opacity:0 !important}" });
  await page.waitForTimeout(1500);
  await shoot(page, "06-lojista-escuro");

  await page.setViewportSize({ width: 1280, height: 860 });
  await page.getByRole("tab", { name: /Pedidos/ }).click();
  await expect(page.getByTestId("merchant-order-row").first()).toBeVisible();
  await shoot(page, "09-lojista-pedidos-escuro");

  await page.getByRole("tab", { name: /Estoque/ }).click();
  await expect(page.getByTestId("stock-row").first()).toBeVisible();
  await shoot(page, "10-lojista-estoque-escuro");

  await page.goto("/");
  await page.getByRole("button", { name: /Assistente/ }).click();
  await page.getByRole("button", { name: /fone/i }).first().click();
  await expect(page.getByTestId("assistant-message").last()).toHaveAttribute(
    "data-status",
    "done",
    {
      timeout: 15_000,
    },
  );
  await shoot(page, "07-assistente-escuro");
});

test("mobile capture", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await theme(page, "light");
  await page.goto("/");
  await expect(page.getByTestId("product-card").first()).toBeVisible();
  await shoot(page, "08-mobile-home");
});
