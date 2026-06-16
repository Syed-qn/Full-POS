import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

describe("design tokens", () => {
  // Values track the active white & grey theme (see tokens.css).
  it.each([
    ["--bg-canvas", "#f4f5f6"],
    ["--bg-surface", "#ffffff"],
    ["--sla-safe", "#2e9e5b"],
    ["--sla-warn", "#d98a1f"],
    ["--sla-critical", "#dc3b3b"],
    ["--sla-breach", "#b91c1c"],
    ["--accent-primary", "#33363b"],
    ["--status-delivered", "#2e9e5b"],
    ["--text-primary", "#1c1e21"],
  ])("defines %s = %s", (name, value) => {
    const re = new RegExp(`${name}:\\s*${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
    expect(css).toMatch(re);
  });
});
