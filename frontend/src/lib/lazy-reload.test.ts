import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadWithReload } from "@/lib/lazy-reload";

describe("loadWithReload", () => {
  beforeEach(() => sessionStorage.clear());

  it("returns the module when the import works", async () => {
    const reload = vi.fn();
    await expect(loadWithReload(async () => ({ ok: true }), reload)).resolves.toEqual({ ok: true });
    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads the page once when a chunk from an older deploy is gone", async () => {
    const reload = vi.fn();
    const failing = () =>
      Promise.reject(new TypeError("Failed to fetch dynamically imported module"));
    void loadWithReload(failing, reload);
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
  });

  it("does not loop: a second failure in the same session is thrown", async () => {
    const reload = vi.fn();
    const failing = () =>
      Promise.reject(new TypeError("Failed to fetch dynamically imported module"));
    void loadWithReload(failing, reload);
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    await expect(loadWithReload(failing, reload)).rejects.toThrow(/dynamically imported/);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("rethrows errors that are not about a missing chunk", async () => {
    const reload = vi.fn();
    await expect(loadWithReload(() => Promise.reject(new Error("boom")), reload)).rejects.toThrow(
      "boom",
    );
    expect(reload).not.toHaveBeenCalled();
  });
});
