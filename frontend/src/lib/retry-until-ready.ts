import { ApiError } from "@/api/client";

interface Options {
  attempts?: number;
  baseMs?: number;
  initialMs?: number;
  wait?: (ms: number) => Promise<void>;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

function notReadyYet(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404);
}

export async function retryUntilReady<T>(
  run: () => Promise<T>,
  { attempts = 6, baseMs = 250, initialMs = 0, wait = sleep }: Options = {},
): Promise<T> {
  if (initialMs > 0) await wait(initialMs);
  let delay = baseMs;
  for (let attempt = 1; ; attempt++) {
    try {
      return await run();
    } catch (error) {
      if (attempt >= attempts || !notReadyYet(error)) throw error;
      await wait(delay);
      delay *= 2;
    }
  }
}
