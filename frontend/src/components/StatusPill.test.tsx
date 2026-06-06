import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("renders human label for FSM status", () => {
    render(<StatusPill status="picked_up" />);
    expect(screen.getByText("Picked Up")).toBeInTheDocument();
  });

  it("sets color CSS var from status", () => {
    render(<StatusPill status="delivered" />);
    const pill = screen.getByText("Delivered");
    expect(pill.style.getPropertyValue("--pill")).toBe("var(--status-delivered)");
  });

  it("falls back to muted for unknown status", () => {
    // @ts-expect-error testing runtime fallback
    render(<StatusPill status="weird_state" />);
    expect(screen.getByText("weird_state")).toBeInTheDocument();
  });
});
