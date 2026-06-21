import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LiveOrderRow } from "./LiveOrderRow";
import type { OrderOut } from "../lib/types";

const o: OrderOut = {
  id: 48, status: "assigned", customer_name: "Omar", customer_phone: "+9715",
  items: [{ dish_number: 201, name: "Karahi", qty: 1, price_aed: "35.00" }],
  total_aed: "40.00", rider_id: 3, rider_name: "Bilal",
  sla_started_at: "2026-06-06T09:33:00Z", prep_deadline: null, cook_estimate_minutes: null, created_at: "2026-06-06T09:32:00Z",
  address: null, lat: null, lng: null,
};

describe("LiveOrderRow", () => {
  it("renders order number, customer, status, rider", () => {
    render(<LiveOrderRow order={o} onOpen={() => {}} />);
    expect(screen.getByText(/#48/)).toBeInTheDocument();
    expect(screen.getByText("Omar")).toBeInTheDocument();
    expect(screen.getByText("Assigned")).toBeInTheDocument();
    expect(screen.getByText("Bilal")).toBeInTheDocument();
  });

  it("calls onOpen when clicked", async () => {
    const onOpen = vi.fn();
    render(<LiveOrderRow order={o} onOpen={onOpen} />);
    await userEvent.click(screen.getByText(/#48/));
    expect(onOpen).toHaveBeenCalledWith(48);
  });

  it("calls onOpen on Enter and Space (keyboard a11y)", async () => {
    const onOpen = vi.fn();
    render(<LiveOrderRow order={o} onOpen={onOpen} />);
    const row = screen.getByRole("button");
    row.focus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    expect(onOpen).toHaveBeenCalledTimes(2);
    expect(onOpen).toHaveBeenCalledWith(48);
  });
});
