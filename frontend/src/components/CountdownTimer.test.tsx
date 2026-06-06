import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CountdownTimer } from "./CountdownTimer";

const NOW = Date.parse("2026-06-06T10:00:00Z");
const iso = (m: number) => new Date(NOW - m * 60_000).toISOString();

describe("CountdownTimer", () => {
  beforeEach(() => vi.useFakeTimers({ now: NOW }));
  afterEach(() => vi.useRealTimers());

  it("renders MM:SS remaining", () => {
    render(<CountdownTimer slaStartedAt={iso(30)} />); // 10 min left
    expect(screen.getByText("10:00")).toBeInTheDocument();
  });

  it("applies critical tier under 10 min", () => {
    render(<CountdownTimer slaStartedAt={iso(31)} />);
    const el = screen.getByTestId("countdown");
    expect(el.style.color).toContain("sla-critical");
  });

  it("freezes at 00:00 on breach", () => {
    render(<CountdownTimer slaStartedAt={iso(45)} />);
    expect(screen.getByText("00:00")).toBeInTheDocument();
  });
});
