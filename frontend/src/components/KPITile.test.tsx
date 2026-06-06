import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KPITile } from "./KPITile";

describe("KPITile", () => {
  it("renders label, value, and positive delta in safe color", () => {
    render(<KPITile label="Revenue Today" value="AED 4,820" delta={12} />);
    expect(screen.getByText("Revenue Today")).toBeInTheDocument();
    expect(screen.getByText("AED 4,820")).toBeInTheDocument();
    const delta = screen.getByText(/↑/);
    expect(delta.style.color).toContain("sla-safe");
  });

  it("renders negative delta in critical color", () => {
    render(<KPITile label="SLA %" value="92%" delta={-4} />);
    expect(screen.getByText(/↓/).style.color).toContain("sla-critical");
  });
});
