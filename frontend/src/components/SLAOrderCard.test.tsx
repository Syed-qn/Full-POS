import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SLAOrderCard } from "./SLAOrderCard";
import type { OrderOut } from "../lib/types";

const NOW = Date.parse("2026-06-06T10:00:00Z");
const iso = (m: number) => new Date(NOW - m * 60_000).toISOString();

function order(over: Partial<OrderOut> = {}): OrderOut {
  return {
    id: 47, status: "preparing", customer_name: "Ali", customer_phone: "+9715",
    items: [{ dish_number: 110, name: "Biryani", qty: 2, price_aed: "22.00" }],
    total_aed: "44.00", rider_id: null, rider_name: null,
    sla_started_at: iso(32), created_at: iso(33), address: "J1", lat: null, lng: null, ...over,
  };
}

describe("SLAOrderCard", () => {
  beforeEach(() => vi.useFakeTimers({ now: NOW }));
  afterEach(() => vi.useRealTimers());

  it("shows order id, customer, and countdown", () => {
    render(<SLAOrderCard order={order()} />);
    expect(screen.getByText(/#47/)).toBeInTheDocument();
    expect(screen.getByText("Ali")).toBeInTheDocument();
    expect(screen.getByTestId("countdown")).toBeInTheDocument();
  });

  it("applies warn lane styling in 10–5 min remaining band", () => {
    render(<SLAOrderCard order={order({ sla_started_at: iso(31) })} />); // 9 min left
    expect(screen.getByTestId("sla-card").className).toContain("warn");
  });

  it("applies critical lane styling under 5 min remaining", () => {
    render(<SLAOrderCard order={order({ sla_started_at: iso(36) })} />); // 4 min left
    expect(screen.getByTestId("sla-card").className).toContain("critical");
  });

  it("applies breach styling past 40 min", () => {
    render(<SLAOrderCard order={order({ sla_started_at: iso(45) })} />);
    expect(screen.getByTestId("sla-card").className).toContain("breach");
  });

  it("fires onClick on Enter and Space (keyboard a11y)", () => {
    const onClick = vi.fn();
    render(<SLAOrderCard order={order()} onClick={onClick} />);
    const card = screen.getByTestId("sla-card");
    card.focus();
    fireEvent.keyDown(card, { key: "Enter" });
    fireEvent.keyDown(card, { key: " " });
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it("renders no dismiss button unless onDismiss is provided", () => {
    render(<SLAOrderCard order={order()} />);
    expect(screen.queryByLabelText(/dismiss alert/i)).not.toBeInTheDocument();
  });

  it("dismiss button fires onDismiss without triggering the card onClick", () => {
    const onClick = vi.fn();
    const onDismiss = vi.fn();
    render(<SLAOrderCard order={order()} onClick={onClick} onDismiss={onDismiss} />);
    fireEvent.click(screen.getByLabelText(/dismiss alert/i));
    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(onClick).not.toHaveBeenCalled();
  });
});
