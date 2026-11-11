import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

async function expectNoA11yViolations(page: Page) {
  const results = await new AxeBuilder({ page })
    .include('[data-testid="assistant-panel"]')
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" | ")}`,
  );
  expect(summary, summary.join("\n")).toEqual([]);
}

const panel = (page: Page) => page.getByRole("dialog", { name: "Assistente de compras" });
const box = (page: Page) => page.getByLabel("Sua pergunta para o assistente");

async function open(page: Page, path = "/") {
  await page.goto(path);
  await expect(page.getByRole("button", { name: /Assistente/ })).toBeVisible();
  await expect(page.getByTestId("product-card").first()).toBeVisible();
}

async function ask(page: Page, question: string) {
  await box(page).fill(question);
  await page.keyboard.press("Enter");
}

test("open from the button, stream an answer, read the trace and follow a citation", async ({
  page,
}) => {
  await open(page);
  await page.getByRole("button", { name: /Assistente/ }).click();
  await expect(panel(page)).toBeVisible();
  await expect(box(page)).toBeFocused();

  await panel(page)
    .getByRole("button", { name: "Quero um fone com cancelamento de ruído" })
    .click();
  await expect(page.getByTestId("typing")).toBeVisible();
  await expect(page.getByTestId("typing")).toContainText("Consultando o catálogo...");
  await expect(page.getByRole("button", { name: "Parar a resposta" })).toBeVisible();

  const reply = page.getByTestId("assistant-message").last();
  await expect(reply).toHaveAttribute("data-status", "done", { timeout: 15_000 });
  await expect(reply).toContainText("Fone Bluetooth Nova ANC");
  await expect(reply.getByTestId("cited-product").first()).toBeVisible();
  await expect(page.getByTestId("assistant-live")).toContainText("Resposta do assistente");

  const toggle = reply.getByRole("button", { name: /Como cheguei nessa resposta/ });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
  await expect(reply.getByText("Busca no catálogo")).toBeVisible();
  await expect(reply.getByText("Trechos recuperados")).toBeVisible();
  await expect(reply.getByTestId("retrieved-chunk").first()).toBeVisible();

  await reply.getByTestId("citation-chip").first().click();
  await expect(page).toHaveURL(/\/produto\/fone-bluetooth-nova/);
  await expect(panel(page)).toBeHidden();
});

test("open from the command palette and ask with the typed text", async ({ page }) => {
  await open(page);
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: /Buscar produtos ou ações/ }).fill("assistente");
  await page.getByRole("option", { name: "Perguntar ao assistente" }).click();
  await expect(panel(page)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(panel(page)).toBeHidden();

  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: /Buscar produtos ou ações/ }).fill("mochila de trilha");
  await page.getByRole("option", { name: /Perguntar: mochila de trilha/ }).click();
  await expect(panel(page)).toBeVisible();
  await expect(page.getByTestId("user-message")).toHaveText("mochila de trilha");
  await expect(page.getByTestId("assistant-message").last()).toContainText(
    "Mochila de Trilha 30L",
    {
      timeout: 15_000,
    },
  );
});

test("keyboard: shortcut toggles, Esc closes, focus is trapped and returns to the button", async ({
  page,
}) => {
  await open(page);
  await page.keyboard.press("Control+/");
  await expect(panel(page)).toBeVisible();
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    expect(await panel(page).evaluate((el) => el.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(panel(page)).toBeHidden();
  await expect(page.getByRole("button", { name: /Assistente/ })).toBeFocused();

  await page.keyboard.press("Control+/");
  await expect(panel(page)).toBeVisible();
  await page.keyboard.press("Control+/");
  await expect(panel(page)).toBeHidden();
});

test("stop the generation and keep the partial answer", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /Assistente/ }).click();
  await ask(page, "o que tem de esporte até R$ 100? resposta lenta");
  const stop = page.getByRole("button", { name: "Parar a resposta" });
  await expect(page.getByTestId("assistant-message").last()).toContainText("Encontrei");
  await stop.click();
  const reply = page.getByTestId("assistant-message").last();
  await expect(reply).toHaveAttribute("data-status", "stopped");
  await expect(reply.getByText("Resposta interrompida.")).toBeVisible();
  await expect(reply.getByRole("button", { name: "Tentar de novo" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Enviar pergunta" })).toBeVisible();
});

test("error shows a clear message and a retry button", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /Assistente/ }).click();
  await ask(page, "simular erro");
  const alert = page.getByRole("alert").filter({ hasText: "indisponível" });
  await expect(alert).toBeVisible();
  await alert.getByRole("button", { name: "Tentar de novo" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "indisponível" })).toBeVisible();
});

test("remembers the conversation after reload and starts a new one", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /Assistente/ }).click();
  await ask(page, "quero um fone com cancelamento de ruído");
  await expect(page.getByTestId("assistant-message").last()).toHaveAttribute(
    "data-status",
    "done",
    {
      timeout: 15_000,
    },
  );
  await ask(page, "esse tem estoque?");
  await expect(page.getByTestId("assistant-message").last()).toContainText("unidades", {
    timeout: 15_000,
  });
  await expect(page.getByTestId("assistant-message").last()).toHaveAttribute("data-status", "done");

  await page.reload();
  await page.getByRole("button", { name: /Assistente/ }).click();
  await expect(page.getByTestId("user-message")).toHaveCount(2);
  await expect(page.getByTestId("assistant-message")).toHaveCount(2);

  await page.getByRole("button", { name: "Nova conversa" }).click();
  await expect(page.getByRole("heading", { name: "Como posso ajudar?" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: /Assistente/ }).click();
  await expect(page.getByRole("heading", { name: "Como posso ajudar?" })).toBeVisible();
});

test("an out of scope question says nothing was found", async ({ page }) => {
  await open(page);
  await page.getByRole("button", { name: /Assistente/ }).click();
  await ask(page, "qual a capital da França?");
  await expect(page.getByTestId("assistant-message").last()).toContainText(
    "Não encontrei no catálogo",
    {
      timeout: 15_000,
    },
  );
});

test("small phones get a full-screen panel without horizontal scroll", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await open(page);
  await page.getByRole("button", { name: "Assistente de compras" }).click();
  const size = await panel(page).boundingBox();
  expect(size?.width).toBeCloseTo(360, 0);
  expect(size?.height).toBeCloseTo(740, 0);
  await ask(page, "o que tem de esporte até R$ 100?");
  await expect(page.getByTestId("assistant-message").last()).toHaveAttribute(
    "data-status",
    "done",
    {
      timeout: 15_000,
    },
  );
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
  const inner = await page.getByRole("log").evaluate((el) => el.scrollWidth <= el.clientWidth);
  expect(inner).toBe(true);
});

for (const theme of ["light", "dark"] as const) {
  test(`a11y: assistant panel with answer and trace (${theme})`, async ({ page }) => {
    await page.addInitScript((t) => localStorage.setItem("praca-theme", t), theme);
    await open(page);
    await page.getByRole("button", { name: /Assistente/ }).click();
    await expectNoA11yViolations(page);

    await ask(page, "quero um fone com cancelamento de ruído");
    const reply = page.getByTestId("assistant-message").last();
    await expect(reply).toHaveAttribute("data-status", "done", { timeout: 15_000 });
    await expect(reply.getByTestId("cited-product").first()).toBeVisible();
    await reply.getByRole("button", { name: /Como cheguei nessa resposta/ }).click();
    await page.waitForTimeout(600);
    await expectNoA11yViolations(page);

    await ask(page, "simular erro");
    await expect(page.getByRole("alert").filter({ hasText: "indisponível" })).toBeVisible();
    await expectNoA11yViolations(page);
  });
}
