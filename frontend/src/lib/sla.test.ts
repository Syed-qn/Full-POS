import { describe, expect, it } from "vitest";
import { formatCountdown, remainingMs, slaTier } from "./sla";

const NOW = Date.parse("2026-06-06T10:00:00Z");
const iso = (minsAgo: number) => new Date(NOW - minsAgo * 60_000).toISOString();

describe("sla", () => {
  it("remainingMs counts down from 40-min window", () => {
    expect(remainingMs(iso(0), NOW)).toBe(40 * 60_000);
    expect(remainingMs(iso(30), NOW)).toBe(10 * 60_000);
    expect(remainingMs(iso(45), NOW)).toBe(-5 * 60_000);
  });

  it("remainingMs returns full window when start is null", () => {
    expect(remainingMs(null, NOW)).toBe(40 * 60_000);
  });

  it.each([
    [0, "safe"],
    [29, "safe"], // 11 min remaining
    [31, "warn"], // 9 min remaining (10–5 min band per brief)
    [36, "critical"], // 4 min remaining (last 5 min per brief)
    [40, "breach"],
    [42, "breach"],
  ])("slaTier at %i min elapsed = %s", (mins, tier) => {
    expect(slaTier(iso(mins), NOW)).toBe(tier);
  });

  it("formatCountdown renders MM:SS, clamps at 00:00", () => {
    expect(formatCountdown(10 * 60_000 + 5_000)).toBe("10:05");
    expect(formatCountdown(-3_000)).toBe("00:00");
  });
});
