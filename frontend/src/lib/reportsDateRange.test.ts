import { describe, expect, it } from "vitest";
import { boundsForPreset } from "./reportsDateRange";

describe("reportsDateRange", () => {
  it("today preset uses the same from and to date", () => {
    const now = new Date("2026-07-03T14:00:00Z");
    expect(boundsForPreset("today", now)).toEqual({
      fromDate: "2026-07-03",
      toDate: "2026-07-03",
      label: "Today",
    });
  });

  it("7d preset spans seven calendar days ending today", () => {
    const now = new Date("2026-07-03T14:00:00Z");
    expect(boundsForPreset("7d", now)).toEqual({
      fromDate: "2026-06-27",
      toDate: "2026-07-03",
      label: "Last 7 days",
    });
  });

  it("all preset omits bounds", () => {
    expect(boundsForPreset("all")).toEqual({
      fromDate: undefined,
      toDate: undefined,
      label: "All time",
    });
  });
});