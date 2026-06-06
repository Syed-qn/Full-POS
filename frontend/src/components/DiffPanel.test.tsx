import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DiffPanel } from "./DiffPanel";
import type { DiffOut } from "../lib/types";

const diff: DiffOut = {
  price_changes: [{ dish_number: 110, name: "Biryani", old_price: "22.00", new_price: "25.00" }],
  added: [{ dish_number: 310, name: "Falooda", price_aed: "12.00" }],
  removed: [{ dish_number: 201, name: "Karahi" }],
  conflicts: [{ dish_number: null, name: "Mystery", reason: "missing number" }],
};

describe("DiffPanel", () => {
  it("renders change counts", () => {
    render(<DiffPanel diff={diff} />);
    expect(screen.getByText(/Changed: 1/)).toBeInTheDocument();
    expect(screen.getByText(/New: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Removed: 1/)).toBeInTheDocument();
    expect(screen.getByText(/Errors: 1/)).toBeInTheDocument();
  });

  it("renders a price-change row with old and new values", () => {
    render(<DiffPanel diff={diff} />);
    expect(screen.getByText(/22\.00/)).toBeInTheDocument();
    expect(screen.getByText(/25\.00/)).toBeInTheDocument();
  });
});
