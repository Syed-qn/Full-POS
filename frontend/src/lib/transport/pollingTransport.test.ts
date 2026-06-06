import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PollingTransport } from "./pollingTransport";

describe("PollingTransport", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("calls fetcher immediately then on interval, pushing to subscriber", async () => {
    let n = 0;
    const fetcher = vi.fn(async () => ++n);
    const received: number[] = [];
    const t = new PollingTransport(fetcher, 3000);
    const unsub = t.subscribe((v) => received.push(v));

    await vi.advanceTimersByTimeAsync(0); // immediate fetch
    expect(received).toEqual([1]);
    await vi.advanceTimersByTimeAsync(3000);
    expect(received).toEqual([1, 2]);
    unsub();
    await vi.advanceTimersByTimeAsync(6000);
    expect(received).toEqual([1, 2]); // stopped after unsubscribe
  });

  it("surfaces fetch errors to onError without stopping the loop", async () => {
    let call = 0;
    const fetcher = vi.fn(async () => {
      call++;
      if (call === 1) throw new Error("net down");
      return call;
    });
    const errors: unknown[] = [];
    const values: number[] = [];
    const t = new PollingTransport(fetcher, 1000);
    t.subscribe((v) => values.push(v), (e) => errors.push(e));

    await vi.advanceTimersByTimeAsync(0);
    expect(errors).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(values).toEqual([2]); // recovered
  });
});
