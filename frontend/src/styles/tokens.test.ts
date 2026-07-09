import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

describe("design tokens", () => {
  // Light professional POS terminal (no dark UI).
  it.each([
    ["--bg-canvas", "#eef0f3"],
    ["--bg-surface", "#ffffff"],
    ["--sla-safe", "#12b76a"],
    ["--sla-warn", "#f79009"],
    ["--sla-critical", "#f04438"],
    ["--sla-breach", "#d92d20"],
    ["--accent-primary", "#175cd3"],
    ["--status-delivered", "#12b76a"],
    ["--text-primary", "#101828"],
  ])("defines %s = %s", (name, value) => {
    const re = new RegExp(`${name}:\\s*${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
    expect(css).toMatch(re);
  });
});
