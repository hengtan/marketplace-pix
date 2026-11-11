import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

async function renderWith(env: { useMocks: boolean; devTools: boolean }) {
  vi.resetModules();
  vi.doMock("@/lib/env", () => ({ env: { apiUrl: "", ...env } }));
  const { DemoHint } = await import("./demo-hint");
  return render(<DemoHint />);
}

describe("DemoHint", () => {
  afterEach(() => vi.doUnmock("@/lib/env"));

  it("shows the mock account only when mocks are on", async () => {
    await renderWith({ useMocks: true, devTools: true });
    expect(screen.getByText(/lojista@praca.dev/)).toBeInTheDocument();
  });

  it("shows the seeded merchant login on a development stack", async () => {
    await renderWith({ useMocks: false, devTools: true });
    expect(screen.getByText(/trilha-sports@marketplace-pix.local/)).toBeInTheDocument();
    expect(screen.getByText("praca1234")).toBeInTheDocument();
    expect(screen.queryByText(/lojista@praca.dev/)).not.toBeInTheDocument();
  });

  it("renders nothing in production", async () => {
    const { container } = await renderWith({ useMocks: false, devTools: false });
    expect(container).toBeEmptyDOMElement();
  });
});
