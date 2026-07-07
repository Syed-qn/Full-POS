import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { startSyncScheduler } from "./scheduler";

vi.mock("./sync", () => ({
  pullSync: vi.fn().mockResolvedValue(undefined),
  pushSync: vi.fn().mockResolvedValue(undefined),
}));

import { pullSync, pushSync } from "./sync";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("startSyncScheduler", () => {
  it("calls pushSync then pullSync on every tick", async () => {
    const handle = startSyncScheduler(
      {} as never,
      "http://api.test",
      fetch,
      () => "tok",
      1000,
    );
    // advanceTimersByTimeAsync (not the sync variant) flushes the awaited
    // pushSync/pullSync microtasks between ticks — the sync variant fires
    // the interval callback but never lets its `await`s resolve before the
    // assertion runs, so pullSync would read as called 0 times.
    await vi.advanceTimersByTimeAsync(3000);
    expect(pushSync).toHaveBeenCalledTimes(3);
    expect(pullSync).toHaveBeenCalledTimes(3);
    handle.stop();
    await vi.advanceTimersByTimeAsync(3000);
    expect(pushSync).toHaveBeenCalledTimes(3); // no more calls after stop()
  });
});
