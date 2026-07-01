import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/render";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrdersScreen } from "./OrdersScreen";
import type { OrderOut } from "../lib/types";

// Mock the orders API so we control the batch fields precisely.
vi.mock("../lib/ordersApi", () => ({ fetchOrders: vi.fn() }));
vi.mock("../lib/orderDetailApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/orderDetailApi")>();
  return {
    ...actual,
    fetchOrderDetail: vi.fn(),
    patchCustomer: vi.fn(),
    patchAddress: vi.fn(),
  };
});

import { fetchOrders } from "../lib/ordersApi";

function order(over: Partial<OrderOut>): OrderOut {
  return {
    id: 1, order_number: "R1-0001", status: "assigned",
    customer_name: "Test", customer_phone: "+9710000000", items: [],
    total_aed: "20.00", rider_id: 2, rider_name: "Asfer",
    sla_started_at: null, prep_deadline: null, cook_estimate_minutes: null,
    created_at: "2026-06-06T09:00:00Z", address: null, lat: null, lng: null,
    batch_id: null, batch_size: null, batch_order_numbers: [],
    ...over,
  };
}

describe("OrdersScreen batching badge", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows a 'together' badge for orders sharing one rider trip", async () => {
    vi.mocked(fetchOrders).mockResolvedValue([
      order({ id: 32, customer_name: "Sara", batch_id: 26, batch_size: 2,
        batch_order_numbers: ["R1-0021", "R1-0022"] }),
      order({ id: 33, customer_name: "Omar", batch_id: 26, batch_size: 2,
        batch_order_numbers: ["R1-0021", "R1-0022"] }),
    ]);
    renderWithProviders(<OrdersScreen />);
    await waitFor(() => expect(screen.getByText("Sara")).toBeInTheDocument());
    const badges = screen.getAllByText(/2 together/i);
    expect(badges).toHaveLength(2);
    expect(badges[0].getAttribute("title")).toContain("R1-0021");
    expect(badges[0].getAttribute("title")).toContain("R1-0022");
  });

  it("shows no badge for a solo order", async () => {
    vi.mocked(fetchOrders).mockResolvedValue([
      order({ id: 40, customer_name: "Lone", batch_id: 30, batch_size: 1,
        batch_order_numbers: ["R1-0040"] }),
    ]);
    renderWithProviders(<OrdersScreen />);
    await waitFor(() => expect(screen.getByText("Lone")).toBeInTheDocument());
    expect(screen.queryByText(/together/i)).not.toBeInTheDocument();
  });
});
