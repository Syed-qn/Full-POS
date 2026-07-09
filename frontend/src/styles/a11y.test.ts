import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const baseCss = readFileSync(resolve(__dirname, "base.css"), "utf8");
const tokensCss = readFileSync(resolve(__dirname, "tokens.css"), "utf8");

describe("a11y baseline CSS", () => {
  it("defines a strong :focus-visible ring (keyboard focus visible)", () => {
    expect(baseCss).toMatch(/:focus-visible\s*\{/);
    expect(baseCss).toMatch(/outline:\s*2px\s+solid\s+var\(--accent-primary\)/);
    expect(baseCss).toMatch(/box-shadow:\s*var\(--focus-ring-strong\)/);
    expect(tokensCss).toMatch(/--focus-ring-strong:/);
  });

  it("covers interactive roles under :focus-visible", () => {
    expect(baseCss).toMatch(/button:focus-visible/);
    expect(baseCss).toMatch(/a:focus-visible/);
    expect(baseCss).toMatch(/\[role="button"\]:focus-visible/);
  });

  it("respects prefers-reduced-motion", () => {
    expect(baseCss).toMatch(/@media\s*\(prefers-reduced-motion:\s*reduce\)/);
    expect(baseCss).toMatch(/animation-duration:\s*0\.001ms\s*!important/);
    expect(baseCss).toMatch(/transition-duration:\s*0\.001ms\s*!important/);
    expect(baseCss).toMatch(/scroll-behavior:\s*auto\s*!important/);
  });

  it("body text on canvas tokens meet WCAG AA contrast intent (dark on light)", () => {
    // --text-primary #101828 on --bg-canvas #eef0f3 is well above 4.5:1.
    expect(tokensCss).toMatch(/--text-primary:\s*#101828/);
    expect(tokensCss).toMatch(/--bg-canvas:\s*#eef0f3/);
    expect(tokensCss).toMatch(/--text-secondary:\s*#475467/);
  });
});
