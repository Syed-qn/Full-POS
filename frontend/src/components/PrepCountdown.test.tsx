import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PrepCountdown } from "./PrepCountdown";

const NOW = Date.parse("2026-06-06T10:00:00Z");
const inMin = (m: number) => new Date(NOW + m * 60_000).toISOString();

describe("PrepCountdown", () => {
  beforeEach(() => vi.useFakeTimers({ now: NOW }));
  afterEach(() => vi.useRealTimers());

  it("renders nothing without a deadline", () => {
    const { container } = render(<PrepCountdown prepDeadline={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("counts down to the plate-by deadline", () => {
    render(<PrepCountdown prepDeadline={inMin(12)} />); // 12 min to plate
    expect(screen.getByText("🍳 Plate in 12:00")).toBeInTheDocument();
  });

  it("shows 'Plate now' once past the deadline", () => {
    render(<PrepCountdown prepDeadline={inMin(-1)} />);
    expect(screen.getByText("🍳 Plate now")).toBeInTheDocument();
    expect(screen.getByTestId("prep-countdown").className).toContain("breach");
  });

  it("uses a custom label (e.g. Start)", () => {
    render(<PrepCountdown prepDeadline={inMin(8)} label="Start" />);
    expect(screen.getByText("🍳 Start in 08:00")).toBeInTheDocument();
  });
});
