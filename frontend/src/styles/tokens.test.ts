import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

describe("design tokens", () => {
  it.each([
    ["--bg-canvas", "#f0f2f5"],
    ["--bg-surface", "#ffffff"],
    ["--sla-safe", "#16a34a"],
    ["--sla-warn", "#d97706"],
    ["--sla-critical", "#dc2626"],
    ["--sla-breach", "#b91c1c"],
    ["--accent-primary", "#2563eb"],
    ["--status-delivered", "#16a34a"],
    ["--text-primary", "#111827"],
  ])("defines %s = %s", (name, value) => {
    const re = new RegExp(`${name}:\\s*${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
    expect(css).toMatch(re);
  });
});
