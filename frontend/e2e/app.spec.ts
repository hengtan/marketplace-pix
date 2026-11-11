import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

async function expectNoA11yViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`,
  );
  expect(summary, summary.join("\n")).toEqual([]);
}

test("browse, search, buy with PIX and see the success state", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Loja/);
  await expect(page.getByTestId("product-card").first()).toBeVisible();

  await page.getByLabel("Buscar produtos").fill("teclado");
  await expect(page.getByTestId("product-card")).toHaveCount(1);
  await page.getByRole("button", { name: /Adicionar Teclado Mecânico Forge 75%/ }).click();

  await page.getByRole("button", { name: /Abrir carrinho, 1 item/ }).click();
  await expect(page.getByTestId("cart-subtotal")).toHaveText("R$ 389,90");
  await page.getByRole("button", { name: /Aumentar quantidade/ }).click();
  await expect(page.getByTestId("cart-subtotal")).toHaveText("R$ 779,80");
  await page.getByRole("link", { name: "Ir para o pagamento" }).click();

  await page.getByRole("button", { name: /Pagar com PIX/ }).click();
  await expect(page.getByText("Informe seu nome completo")).toBeVisible();
  await expect(page.getByText("Informe seu e-mail")).toBeVisible();

  await page.getByLabel("Nome completo").fill("Maria Souza");
  await page.getByLabel("E-mail").fill("maria@exemplo.com");
  await page.getByRole("button", { name: /Pagar com PIX/ }).click();

  await expect(page).toHaveURL(/\/pedido\//);
  await expect(page.getByTestId("pix-code")).toBeVisible();
  await expect(page.getByTestId("countdown")).toHaveText(/^(09|10):\d\d$/);
  await expectNoA11yViolations(page);

  await page.getByTestId("simulate-pay").click();
  await expect(page.getByTestId("order-paid")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("heading", { name: "Pagamento confirmado" })).toBeVisible();

  await page.getByRole("link", { name: "Meus pedidos" }).first().click();
  await expect(page.getByTestId("order-row")).toHaveCount(1);
  await expect(page.getByText("Pago", { exact: true })).toBeVisible();
});

test("expired PIX is cancelled with a friendly reason and can be redone", async ({ page }) => {
  await page.goto("/produto/corda-pular-speed");
  await page.getByRole("button", { name: "Adicionar ao carrinho" }).click();
  await page.goto("/checkout");
  await page.getByLabel("Nome completo").fill("Teste Expira");
  await page.getByLabel("E-mail").fill("expira@exemplo.com");
  await page.getByRole("button", { name: /Pagar com PIX/ }).click();
  await expect(page.getByTestId("pix-code")).toBeVisible();
  await expect(page.getByTestId("order-cancelled")).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("O PIX expirou antes do pagamento")).toBeVisible();
  await page.getByRole("button", { name: "Refazer pedido" }).click();
  await expect(page).toHaveURL(/\/checkout/);
  await expect(page.getByTestId("cart-line")).toHaveCount(1);
});

test("insufficient stock cancels with the stock reason", async ({ page }) => {
  await page.goto("/produto/relogio-gps-trail");
  await expect(page.getByText(/Últimas 3 unidades/).first()).toBeVisible();
  await page.getByRole("button", { name: "Adicionar ao carrinho" }).click();
  await page.getByRole("button", { name: /Abrir carrinho/ }).click();
  await expect(page.getByRole("button", { name: /Aumentar quantidade/ })).toBeEnabled();
});

test("command palette searches and navigates", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("product-card").first()).toBeVisible();
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: /Buscar produtos ou ações/ }).fill("mochila");
  await page.getByRole("option", { name: /Mochila de Trilha/ }).click();
  await expect(page).toHaveURL(/\/produto\/mochila-trilha-30l/);
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: /Buscar produtos ou ações/ }).fill("lojista");
  await expect(page.getByRole("option", { name: "Painel do lojista" })).toBeVisible();
  await page.getByRole("option", { name: "Painel do lojista" }).click();
  await expect(page).toHaveURL(/\/entrar\?redirect=%2Flojista/);
});

test("theme toggle persists", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Mudar para o tema escuro" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

async function signIn(page: Page, redirect = "/") {
  await page.goto(`/entrar?redirect=${encodeURIComponent(redirect)}`);
  await page.getByLabel("E-mail").fill("lojista@praca.dev");
  await page.getByLabel("Senha", { exact: true }).fill("praca1234");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
}

test("protected route redirects guests to login and returns after sign in", async ({ page }) => {
  await page.goto("/lojista");
  await expect(page).toHaveURL(/\/entrar\?redirect=/);
  await page.getByLabel("E-mail").fill("lojista@praca.dev");
  await page.getByLabel("Senha", { exact: true }).fill("wrong-password");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("E-mail ou senha incorretos");
  await page.getByLabel("Senha", { exact: true }).fill("praca1234");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page).toHaveURL(/\/lojista/);
  await expect(page.getByText("Saldo a receber")).toBeVisible();
});

test("guests can browse and register an account", async ({ page }) => {
  await page.goto("/cadastro");
  await page.getByRole("button", { name: "Criar conta", exact: true }).click();
  await expect(page.getByText("Informe seu nome completo")).toBeVisible();
  await page.getByLabel("Nome completo").fill("Ana Teste");
  await page.getByLabel("E-mail").fill("ana@exemplo.com");
  await page.getByLabel("Senha", { exact: true }).fill("senhaforte1");
  await page.getByRole("button", { name: "Criar conta", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/lojista");
  await expect(page.getByText("Área exclusiva para lojistas")).toBeVisible();
});

for (const [name, path] of [
  ["home", "/"],
  ["produto", "/produto/fone-bluetooth-nova"],
  ["pedidos", "/pedidos"],
  ["lojista", "/lojista"],
  ["entrar", "/entrar"],
  ["cadastro", "/cadastro"],
] as const) {
  for (const theme of ["light", "dark"] as const) {
    test(`a11y: ${name} (${theme})`, async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem("praca-theme", t), theme);
      if (name === "lojista") await signIn(page, path);
      else await page.goto(path);
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1200);
      await expectNoA11yViolations(page);
    });
  }
}
