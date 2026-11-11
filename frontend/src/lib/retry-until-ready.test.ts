import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import { retryUntilReady } from "@/lib/retry-until-ready";

const notYet = () => new ApiError("forbidden", 403);
const instantly = async () => {};

describe("retryUntilReady", () => {
  it("returns right away when the first attempt works", async () => {
    const run = vi.fn().mockResolvedValue("ok");
    await expect(retryUntilReady(run, { wait: instantly })).resolves.toBe("ok");
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("keeps trying while the stock row is still being created (403 or 404)", async () => {
    const run = vi
      .fn()
      .mockRejectedValueOnce(notYet())
      .mockRejectedValueOnce(new ApiError("not found", 404))
      .mockResolvedValue("ok");
    await expect(retryUntilReady(run, { wait: instantly })).resolves.toBe("ok");
    expect(run).toHaveBeenCalledTimes(3);
  });

  it("gives up after the configured attempts and throws the last error", async () => {
    const run = vi.fn().mockRejectedValue(notYet());
    await expect(retryUntilReady(run, { attempts: 4, wait: instantly })).rejects.toThrow(
      "forbidden",
    );
    expect(run).toHaveBeenCalledTimes(4);
  });

  it("does not retry errors that waiting cannot fix", async () => {
    const run = vi.fn().mockRejectedValue(new ApiError("invalid", 422));
    await expect(retryUntilReady(run, { wait: instantly })).rejects.toThrow("invalid");
    expect(run).toHaveBeenCalledTimes(1);
  });

  it("waits a little longer between each attempt", async () => {
    const delays: number[] = [];
    const run = vi.fn().mockRejectedValue(notYet());
    await retryUntilReady(run, {
      attempts: 4,
      baseMs: 100,
      wait: async (ms) => {
        delays.push(ms);
      },
    }).catch(() => undefined);
    expect(delays).toEqual([100, 200, 400]);
  });

  it("can wait before the very first attempt so a slow event does not cause a failed request", async () => {
    const delays: number[] = [];
    const run = vi.fn().mockResolvedValue("ok");
    await retryUntilReady(run, {
      initialMs: 500,
      wait: async (ms) => {
        delays.push(ms);
      },
    });
    expect(delays).toEqual([500]);
    expect(run).toHaveBeenCalledTimes(1);
  });
});
