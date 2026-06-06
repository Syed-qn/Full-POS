import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

describe("design tokens", () => {
  it.each([
    ["--bg-canvas", "#0d0f12"],
    ["--bg-surface", "#141720"],
    ["--sla-safe", "#1adb8e"],
    ["--sla-warn", "#f5a623"],
    ["--sla-critical", "#ff3d55"],
    ["--sla-breach", "#ff1a37"],
    ["--accent-primary", "#3d8bff"],
    ["--status-delivered", "#1adb8e"],
    ["--text-primary", "#e8ecf5"],
  ])("defines %s = %s", (name, value) => {
    const re = new RegExp(`${name}:\\s*${value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`);
    expect(css).toMatch(re);
  });
});
