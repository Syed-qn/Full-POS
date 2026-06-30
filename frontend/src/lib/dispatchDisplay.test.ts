import { describe, it, expect } from "vitest";
import { formatEngineLabel, formatRejectionReason } from "./dispatchDisplay";

describe("dispatchDisplay", () => {
  it("formats known rejection reasons", () => {
    expect(formatRejectionReason("sla_risk")).toMatch(/SLA risk/i);
    expect(formatRejectionReason("proximity")).toMatch(/batch mate/i);
  });

  it("formats engine labels with fallback flag", () => {
    expect(formatEngineLabel("ortools")).toMatch(/OR-Tools/);
    expect(formatEngineLabel("greedy", true)).toMatch(/fallback/i);
  });
});