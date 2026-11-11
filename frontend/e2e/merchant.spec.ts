import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

const API = "http://localhost:8000";

async function a11y(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`,
  );
  expect(summary, summary.join("\n")).toEqual([]);
}

async function signIn(page: Page, email = "lojista@praca.dev", redirect = "/lojista") {
  await page.goto(`/entrar?redirect=${encodeURIComponent(redirect)}`);
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Senha", { exact: true }).fill("praca1234");
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await expect(page).toHaveURL(/\/lojista/);
  await expect(page.locator("[role=tablist]")).toBeVisible();
  await page.waitForLoadState("networkidle");
}

const TABS = [
  ["visao-geral", "Visão geral", "Saldo a receber"],
  ["pedidos", "Pedidos", "Atualiza sozinho"],
  ["estoque", "Estoque", "Clique no número disponível"],
  ["produtos", "Produtos", "Edite nome e preço"],
  ["extrato", "Extrato", "Lançamentos do livro-razão"],
] as const;

test("tabs live in the URL, animate and keep the selected period", async ({ page }) => {
  await signIn(page);
  await expect(page.getByText("Saldo a receber")).toBeVisible();
  await page.getByRole("radio", { name: "7 dias" }).click();
  await expect(page).toHaveURL(/dias=7/);

  await page.getByRole("tab", { name: /Estoque/ }).click();
  await expect(page).toHaveURL(/aba=estoque/);
  await expect(page).toHaveURL(/dias=7/);
  await expect(page.getByRole("tab", { name: /Estoque/ })).toHaveAttribute("aria-selected", "true");

  await page.getByRole("tab", { name: "Visão geral" }).click();
  await expect(page.getByRole("radio", { name: "7 dias" })).toHaveAttribute("aria-checked", "true");

  await page.getByRole("tab", { name: "Visão geral" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("tab", { name: /Pedidos/ })).toBeFocused();
  await expect(page).toHaveURL(/aba=pedidos/);

  await page.goto("/lojista?aba=extrato&dias=14");
  await expect(page.getByRole("tab", { name: "Extrato" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("radio", { name: "14 dias" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
});

test("overview shows period comparison, alerts that lead to the right tab and the heatmap", async ({
  page,
}) => {
  await signIn(page);
  await expect(page.getByText("Ticket médio").first()).toBeVisible();
  await expect(page.getByText("Taxa efetiva")).toBeVisible();
  await expect(page.getByText(/vs 30 dias anteriores/).first()).toBeVisible();
  await expect(page.getByRole("table", { name: /Calendário de vendas/ })).toBeVisible();
  await expect(page.getByText("Melhor dia")).toBeVisible();

  await page.getByRole("button", { name: /estoque baixo/ }).click();
  await expect(page).toHaveURL(/aba=estoque/);
  await page.getByRole("tab", { name: "Visão geral" }).click();
  await page.getByRole("button", { name: /aguardando pagamento há mais de 5 minutos/ }).click();
  await expect(page).toHaveURL(/aba=pedidos/);
});

test("orders: filter, search, open the drawer, close it with Esc and restore focus", async ({
  page,
}) => {
  await signIn(page, "lojista@praca.dev", "/lojista?aba=pedidos");
  const rows = page.getByTestId("merchant-order-row");
  await expect(rows.first()).toBeVisible();
  const all = await rows.count();
  expect(all).toBeGreaterThan(3);

  await page.getByRole("radio", { name: /Aguardando/ }).click();
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("Aguardando PIX");

  await page.getByRole("radio", { name: /Todos/ }).click();
  await page.getByRole("searchbox", { name: /Buscar pedidos/ }).fill("capacete");
  await expect(rows.first()).toContainText("Capacete");
  await page.getByRole("searchbox", { name: /Buscar pedidos/ }).fill("zzzz");
  await expect(page.getByText("Nenhum pedido encontrado")).toBeVisible();
  await page.getByRole("button", { name: "Limpar filtros" }).click();

  const opener = rows.first().getByRole("button", { name: /Abrir pedido/ });
  await opener.click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toBeVisible();
  await expect(page).toHaveURL(/pedido=/);
  await expect(drawer.getByText("Taxa da plataforma (10%)")).toBeVisible();
  await expect(drawer.getByRole("list", { name: /Linha do tempo/ })).toBeVisible();
  await page.waitForTimeout(900);
  await a11y(page);

  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(page).not.toHaveURL(/pedido=/);
});

test("orders refresh by themselves and announce a new sale", async ({ page }) => {
  await signIn(page, "lojista@praca.dev", "/lojista?aba=pedidos");
  await expect(page.getByTestId("merchant-order-row").first()).toBeVisible();
  const before = await page.getByRole("radio", { name: /Pagos/ }).textContent();

  await page.evaluate(async (api) => {
    const product = await (
      await fetch(`${api}/api/catalog/products/slug/corda-pular-speed`)
    ).json();
    const created = await fetch(`${api}/api/orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({
        customer_id: "guest-e2e-live",
        customer_name: "Cliente Ao Vivo",
        customer_email: "vivo@exemplo.com",
        items: [{ product_id: product.id, quantity: 1 }],
      }),
    });
    const { id } = await created.json();
    const payment = await (await fetch(`${api}/api/payments/by-order/${id}`)).json();
    await fetch(`${api}/api/payments/dev/psp/charges/${payment.psp_charge_id}/pay`, {
      method: "POST",
    });
  }, API);

  await expect(page.getByText(/Nova venda de R\$ 49,90/)).toBeVisible({ timeout: 25_000 });
  await expect(page.getByTestId("merchant-order-row").first()).toContainText("Cliente Ao Vivo");
  await expect(page.getByRole("radio", { name: /Pagos/ })).not.toHaveText(before ?? "");
});

test("stock: validates inline, saves optimistically and highlights critical items", async ({
  page,
}) => {
  await signIn(page, "lojista@praca.dev", "/lojista?aba=estoque");
  const rows = page.getByTestId("stock-row");
  await expect(rows.first()).toContainText("Relógio GPS Trail");
  await expect(rows.first()).toContainText("Crítico");

  await rows
    .first()
    .getByRole("button", { name: /Editar estoque/ })
    .click();
  const field = page.getByRole("textbox", { name: /Novo estoque disponível/ });
  await field.fill("-4");
  await field.press("Enter");
  await expect(page.getByRole("alert").filter({ hasText: "números inteiros" })).toBeVisible();
  await field.fill("40");
  await field.press("Enter");
  await expect(
    page
      .getByTestId("stock-row")
      .filter({ hasText: "Relógio GPS Trail" })
      .getByRole("button", { name: /40 disponíveis/ }),
  ).toBeVisible();
  await expect(
    page.getByTestId("stock-row").filter({ hasText: "Relógio GPS Trail" }),
  ).toContainText("Saudável");

  await page.getByRole("checkbox", { name: "Selecionar Corda de Pular Speed" }).check();
  await page.getByRole("checkbox", { name: "Selecionar Tapete de Yoga Grip" }).check();
  await page.getByRole("button", { name: "Somar 10 unidades" }).click();
  await expect(
    page
      .getByTestId("stock-row")
      .filter({ hasText: "Tapete de Yoga Grip" })
      .getByRole("button", { name: /35 disponíveis/ }),
  ).toBeVisible();
});

test("stock: rolls back and explains when the account lacks permission", async ({ page }) => {
  await signIn(page, "leitura@praca.dev", "/lojista?aba=estoque");
  const row = page.getByTestId("stock-row").filter({ hasText: "Fone Bluetooth Nova ANC" });
  await row.getByRole("button", { name: /Editar estoque/ }).click();
  const field = page.getByRole("textbox", { name: /Novo estoque disponível/ });
  await field.fill("7");
  await field.press("Enter");
  await expect(page.getByText("Estoque não alterado")).toBeVisible();
  await expect(page.getByText(/não tem permissão para alterar este estoque/)).toBeVisible();
  await expect(
    page
      .getByTestId("stock-row")
      .filter({ hasText: "Fone Bluetooth Nova ANC" })
      .getByRole("button", { name: /25 disponíveis/ }),
  ).toBeVisible();
});

test("products: create with validation, edit the price and deactivate", async ({ page }) => {
  await signIn(page, "lojista@praca.dev", "/lojista?aba=produtos");
  await expect(page.getByTestId("merchant-product").first()).toBeVisible();
  const before = await page.getByTestId("merchant-product").count();

  await page.getByRole("button", { name: "Novo produto" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Criar produto" }).click();
  await expect(dialog.getByText("Use ao menos 3 caracteres")).toBeVisible();
  await expect(dialog.getByText("Informe um preço válido, como 49,90")).toBeVisible();
  await expect(dialog.getByText("Escolha uma categoria")).toBeVisible();

  await dialog.getByLabel("Nome").fill("Corda de Aço Pro");
  await dialog.getByLabel("Descrição").fill("Corda de pular com cabo de aço revestido.");
  await dialog.getByLabel("Preço (R$)").fill("59,90");
  await dialog.getByLabel("Categoria").selectOption("esporte");
  await dialog.getByLabel("Estoque inicial").fill("12");
  await dialog.getByRole("button", { name: "Criar produto" }).click();
  await expect(page.getByText("Produto criado, ainda sem estoque")).toBeVisible();
  await expect(page.getByTestId("merchant-product").first()).toContainText(
    "Sem estoque cadastrado",
  );
  await expect(page.getByTestId("merchant-product")).toHaveCount(before + 1);
  await expect(page.getByTestId("merchant-product").first()).toContainText("R$ 59,90");

  await page.getByRole("button", { name: "Editar Corda de Aço Pro" }).click();
  await page.getByRole("dialog").getByLabel("Preço (R$)").fill("64,90");
  await page.getByRole("dialog").getByRole("button", { name: "Salvar alterações" }).click();
  await expect(page.getByTestId("merchant-product").first()).toContainText("R$ 64,90");

  await page.getByRole("button", { name: "Desativar Corda de Aço Pro" }).click();
  await expect(page.getByRole("dialog", { name: "Desativar produto?" })).toBeVisible();
  await page.waitForTimeout(700);
  await a11y(page);
  await page.getByRole("dialog").getByRole("button", { name: "Desativar" }).click();
  await expect(page.getByTestId("merchant-product")).toHaveCount(before);

  const inactive = page.getByTestId("inactive-products");
  await expect(inactive).toContainText("Corda de Aço Pro");
  await a11y(page);
  await inactive.getByRole("button", { name: "Reativar Corda de Aço Pro" }).click();
  await expect(page.getByTestId("merchant-product")).toHaveCount(before + 1);
  await expect(page.getByTestId("merchant-product").first()).toContainText("R$ 64,90");
  await expect(page.getByTestId("inactive-products")).toHaveCount(0);
});

test("products: a duplicated name and a missing permission show clear messages", async ({
  page,
}) => {
  await signIn(page, "lojista@praca.dev", "/lojista?aba=produtos&novo=true");
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Nome").fill("Mochila de Trilha 30L");
  await dialog.getByLabel("Descrição").fill("Outra mochila com o mesmo nome.");
  await dialog.getByLabel("Preço (R$)").fill("10");
  await dialog.getByLabel("Categoria").selectOption("esporte");
  await dialog.getByRole("button", { name: "Criar produto" }).click();
  await expect(dialog.getByText("Já existe um produto com esse nome")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto("/entrar?redirect=%2Flojista%3Faba%3Dprodutos");
  await page.evaluate(() => sessionStorage.clear());
  await signIn(page, "leitura@praca.dev", "/lojista?aba=produtos&novo=true");
  const d2 = page.getByRole("dialog");
  await d2.getByLabel("Nome").fill("Produto Sem Permissão");
  await d2.getByLabel("Descrição").fill("Não deve ser criado por esta conta.");
  await d2.getByLabel("Preço (R$)").fill("10");
  await d2.getByLabel("Categoria").selectOption("tecnologia");
  await d2.getByRole("button", { name: "Criar produto" }).click();
  await expect(d2.getByRole("alert")).toContainText("não tem permissão para alterar o catálogo");
});

test("statement: filters by type, groups by day, exports CSV and copies a value", async ({
  context,
  page,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await signIn(page, "lojista@praca.dev", "/lojista?aba=extrato");
  await expect(page.getByRole("rowgroup").first()).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Saldo acumulado" })).toBeVisible();

  await page.getByRole("radio", { name: "Débitos" }).click();
  await expect(page.getByText("Nenhum lançamento", { exact: true })).toBeVisible();
  await page.getByRole("radio", { name: "Tudo" }).click();

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Exportar CSV" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/^extrato-trilha-sports-\d{4}-\d{2}-\d{2}\.csv$/);

  await page
    .getByRole("button", { name: /Copiar valor/ })
    .first()
    .click();
  await expect(page.getByText("Valor copiado")).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(/^\d+,\d{2}$/);
});

test("shortcuts and the command palette move around the panel", async ({ page }) => {
  await signIn(page);
  await expect(page.getByText("Saldo a receber")).toBeVisible();
  await page.keyboard.press("g");
  await page.keyboard.press("e");
  await expect(page).toHaveURL(/aba=estoque/);
  await page.keyboard.press("g");
  await page.keyboard.press("x");
  await expect(page).toHaveURL(/aba=extrato/);
  await page.keyboard.press("g");
  await page.keyboard.press("p");
  await expect(page).toHaveURL(/aba=pedidos/);
  await page.keyboard.press("g");
  await page.keyboard.press("v");
  await expect(page.getByRole("tab", { name: "Visão geral" })).toHaveAttribute(
    "aria-selected",
    "true",
  );

  await page.keyboard.press("Shift+?");
  await expect(page.getByRole("dialog", { name: "Atalhos de teclado" })).toBeVisible();
  await page.waitForTimeout(700);
  await a11y(page);
  await page.keyboard.press("Escape");

  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: /Buscar produtos ou ações/ }).fill("ir para estoque");
  await page.getByRole("option", { name: "Ir para Estoque", exact: true }).click();
  await expect(page).toHaveURL(/aba=estoque/);

  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: /Buscar produtos ou ações/ }).fill("novo produto");
  await page.getByRole("option", { name: "Novo produto", exact: true }).click();
  await expect(page).toHaveURL(/aba=produtos/);
  await expect(page.getByRole("dialog", { name: "Novo produto" })).toBeVisible();
});

test("admin sees every store and the reconciliation, and a clear note on store-only tabs", async ({
  page,
}) => {
  await signIn(page, "admin@praca.dev");
  await expect(page.getByText(/Livro-razão conciliado, \d+ lançamentos/)).toBeVisible();
  await expect(page.getByRole("radio", { name: "Casa Lume" })).toBeVisible();
  await page.getByRole("tab", { name: /Pedidos/ }).click();
  await expect(page.getByText("Contas de administrador não têm pedidos de loja")).toBeVisible();
  await page.getByRole("tab", { name: /Estoque/ }).click();
  await expect(page.getByTestId("stock-row").first()).toBeVisible();
});

for (const [slug, name, marker] of TABS) {
  for (const theme of ["light", "dark"] as const) {
    test(`a11y: merchant ${name} (${theme})`, async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem("praca-theme", t), theme);
      await signIn(page, "lojista@praca.dev", `/lojista?aba=${slug}`);
      await expect(page.getByText(marker).first()).toBeVisible();
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(1500);
      await a11y(page);
    });
  }
}

test("no console errors while walking every tab", async ({ page }) => {
  const problems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning") problems.push(`${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await signIn(page);
  for (const [slug, , marker] of TABS) {
    await page.goto(`/lojista?aba=${slug}`);
    await expect(page.getByText(marker).first()).toBeVisible();
  }
  expect(problems).toEqual([]);
});

test("reduced motion still renders every tab", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signIn(page);
  for (const [slug, , marker] of TABS) {
    await page.goto(`/lojista?aba=${slug}`);
    await expect(page.getByText(marker).first()).toBeVisible();
  }
});
