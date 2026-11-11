import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import { env } from "@/lib/env";
import { server } from "@/mocks/server";
import { useAuth } from "@/store/auth";
import { useCart } from "@/store/cart";
import { useUi } from "@/store/ui";
import { renderWithRouter } from "@/test/utils";
import { AssistantLauncher } from "./launcher";
import { AssistantPanel } from "./panel";
import { useAssistant } from "./store";

async function setup() {
  const user = userEvent.setup();
  await renderWithRouter(
    <>
      <AssistantLauncher />
      <AssistantPanel />
    </>,
  );
  return user;
}

beforeEach(() => {
  useAssistant.getState().reset();
  useUi.setState({ assistantOpen: false, paletteOpen: false, cartOpen: false });
  useCart.setState({ lines: [] });
});

describe("assistant panel", () => {
  it("opens from the launcher with suggestions and closes with Esc, returning focus", async () => {
    const user = await setup();
    const launcher = screen.getByRole("button", { name: /Assistente/ });
    await user.click(launcher);

    const dialog = await screen.findByRole("dialog", { name: "Assistente de compras" });
    expect(within(dialog).getByRole("heading", { name: "Como posso ajudar?" })).toBeVisible();
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(3);
    await waitFor(() =>
      expect(screen.getByLabelText("Sua pergunta para o assistente")).toHaveFocus(),
    );

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(launcher).toHaveFocus();
  });

  it("toggles with the keyboard shortcut", async () => {
    const user = await setup();
    await user.keyboard("{Control>}/{/Control}");
    expect(await screen.findByRole("dialog")).toBeVisible();
    await user.keyboard("{Control>}/{/Control}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("asks a question, shows cited products, the trace and adds to the cart", async () => {
    const user = await setup();
    await user.click(screen.getByRole("button", { name: /Assistente/ }));
    await user.type(
      await screen.findByLabelText("Sua pergunta para o assistente"),
      "quero um fone com cancelamento de ruído{Enter}",
    );

    const sent = await screen.findByText("quero um fone com cancelamento de ruído");
    await waitFor(() => expect(sent).toBeVisible());
    const cards = await screen.findAllByTestId("cited-product", undefined, { timeout: 4000 });
    expect(cards.length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("citation-chip")[0]).toHaveAttribute(
      "href",
      "/produto/fone-bluetooth-nova",
    );

    const toggle = screen.getByRole("button", { name: /Como cheguei nessa resposta/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(screen.getByText("Busca no catálogo")).toBeVisible());
    expect(screen.getAllByTestId("retrieved-chunk").length).toBeGreaterThan(0);

    const add = await screen.findByRole("button", {
      name: "Adicionar Fone Bluetooth Nova ANC ao carrinho",
    });
    await waitFor(() => expect(add).toBeEnabled());
    await user.click(add);
    expect(useCart.getState().lines.map((l) => l.slug)).toContain("fone-bluetooth-nova");
  });

  it("shows a friendly error with a retry button", async () => {
    const user = await setup();
    await user.click(screen.getByRole("button", { name: /Assistente/ }));
    await user.type(
      await screen.findByLabelText("Sua pergunta para o assistente"),
      "simular erro{Enter}",
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/indisponível/);
    expect(within(alert).getByRole("button", { name: "Tentar de novo" })).toBeVisible();
  });

  async function ask(text: string) {
    const user = await setup();
    await user.click(screen.getByRole("button", { name: /Assistente/ }));
    await user.type(
      await screen.findByLabelText("Sua pergunta para o assistente"),
      `${text}{Enter}`,
    );
    return user;
  }

  it("explains a daily budget limit with the Retry-After and offers no retry", async () => {
    await ask("simular limite");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/limite de uso do assistente por hoje/);
    expect(alert).toHaveTextContent(/em 2 horas/);
    expect(within(alert).queryByRole("button", { name: /Tentar de novo/ })).toBeNull();
  });

  it("tells the user to start a new conversation when the session budget is over", async () => {
    await ask("simular limite da sessao");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Comece uma nova conversa/);
    expect(alert).toHaveTextContent(/30 minutos/);
  });

  it("counts down the Retry-After of a rate limit before allowing a retry", async () => {
    await ask("simular muitas perguntas");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Aguarde 20 segundos/);
    const retry = within(alert).getByRole("button", { name: /Tentar de novo em 20 segundos/ });
    expect(retry).toBeDisabled();
  });

  it("shows a friendly 503 with the wait time", async () => {
    await ask("simular indisponivel");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/indisponível agora/);
    expect(alert).toHaveTextContent(/em 30 segundos/);
  });

  it("flags a degraded answer coming from a stream warning", async () => {
    await ask("simular degradado fone");
    const notice = await screen.findByTestId("degraded-notice");
    expect(notice).toHaveTextContent(/modelo do assistente está indisponível/);
    await screen.findAllByTestId("cited-product");
  });

  it("sends the Bearer token of the signed in user", async () => {
    let header: string | null = null;
    server.use(
      http.post(`${env.apiUrl.replace(/\/$/, "")}/api/assistant/chat/stream`, ({ request }) => {
        header = request.headers.get("Authorization");
        return HttpResponse.json({ detail: "stop here" }, { status: 400 });
      }),
    );
    useAuth.setState({ accessToken: "acc.test-token", refreshToken: null });
    await ask("quero um fone");
    await screen.findByRole("alert");
    expect(header).toBe("Bearer acc.test-token");
    useAuth.getState().clear();
  });

  it("sends no Authorization header to guests", async () => {
    let header: string | null = "unset";
    server.use(
      http.post(`${env.apiUrl.replace(/\/$/, "")}/api/assistant/chat/stream`, ({ request }) => {
        header = request.headers.get("Authorization");
        return HttpResponse.json({ detail: "stop here" }, { status: 400 });
      }),
    );
    await ask("quero um fone");
    await screen.findByRole("alert");
    expect(header).toBeNull();
  });

  it("starts a new conversation", async () => {
    const user = await setup();
    await user.click(screen.getByRole("button", { name: /Assistente/ }));
    await user.click(
      await screen.findByRole("button", { name: "Quero um fone com cancelamento de ruído" }),
    );
    await screen.findByTestId("assistant-message");
    await user.click(screen.getByRole("button", { name: "Nova conversa" }));
    expect(await screen.findByRole("heading", { name: "Como posso ajudar?" })).toBeVisible();
    expect(screen.queryByTestId("assistant-message")).toBeNull();
  });

  it("disables sending an empty message and exposes a stop button while streaming", async () => {
    const user = await setup();
    await user.click(screen.getByRole("button", { name: /Assistente/ }));
    expect(await screen.findByRole("button", { name: "Enviar pergunta" })).toBeDisabled();
    useAssistant.setState({ streaming: true });
    expect(await screen.findByRole("button", { name: "Parar a resposta" })).toBeVisible();
    useAssistant.setState({ streaming: false });
  });
});
