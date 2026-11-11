import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PixPanel } from "./pix-panel";

const CODE = "00020126580014BR.GOV.BCB.PIX0136abc";

describe("PixPanel", () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it("renders the code, amount and a ticking countdown", () => {
    const expires = new Date(Date.now() + 90_000).toISOString();
    render(<PixPanel pixCode={CODE} amountCents={34990} expiresAt={expires} />);
    expect(screen.getByTestId("pix-code")).toHaveTextContent(CODE);
    expect(screen.getByTestId("pix-amount")).toHaveTextContent("R$ 349,90");
    expect(screen.getByTestId("countdown")).toHaveTextContent("01:30");
    act(() => {
      vi.advanceTimersByTime(31_000);
    });
    expect(screen.getByTestId("countdown")).toHaveTextContent("00:59");
  });

  it("copies the code and gives feedback", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    render(
      <PixPanel
        pixCode={CODE}
        amountCents={100}
        expiresAt={new Date(Date.now() + 60_000).toISOString()}
      />,
    );
    await user.click(screen.getByTestId("copy-pix"));
    expect(writeText).toHaveBeenCalledWith(CODE);
    expect(await screen.findByText("Código copiado")).toBeInTheDocument();
  });

  it("shows the expired state and notifies when the countdown ends", () => {
    const onExpired = vi.fn();
    render(
      <PixPanel
        pixCode={CODE}
        amountCents={100}
        expiresAt={new Date(Date.now() + 2_000).toISOString()}
        onExpired={onExpired}
      />,
    );
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    expect(screen.getByTestId("countdown")).toHaveTextContent("00:00");
    expect(screen.getByTestId("copy-pix")).toBeDisabled();
    expect(onExpired).toHaveBeenCalled();
  });

  it("only shows the simulate button when a handler is provided", async () => {
    const onSimulate = vi.fn();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const expires = new Date(Date.now() + 60_000).toISOString();
    const { rerender } = render(<PixPanel pixCode={CODE} amountCents={100} expiresAt={expires} />);
    expect(screen.queryByTestId("simulate-pay")).toBeNull();
    rerender(
      <PixPanel pixCode={CODE} amountCents={100} expiresAt={expires} onSimulate={onSimulate} />,
    );
    await user.click(screen.getByTestId("simulate-pay"));
    expect(onSimulate).toHaveBeenCalledTimes(1);
  });
});
