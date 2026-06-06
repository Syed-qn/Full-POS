import { render, screen } from "@testing-library/react";
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

  it("applies critical lane styling under 10 min remaining", () => {
    render(<SLAOrderCard order={order({ sla_started_at: iso(31) })} />);
    expect(screen.getByTestId("sla-card").className).toContain("critical");
  });

  it("applies breach styling past 40 min", () => {
    render(<SLAOrderCard order={order({ sla_started_at: iso(45) })} />);
    expect(screen.getByTestId("sla-card").className).toContain("breach");
  });
});
