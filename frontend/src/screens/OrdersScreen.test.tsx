import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OrdersScreen } from "./OrdersScreen";

// Stub out the detail API so opening a drawer doesn't produce unhandled rejections
// (the full drawer behaviour is covered in OrderDetailDrawer.test.tsx)
vi.mock("../lib/orderDetailApi", () => ({
  fetchOrderDetail: vi.fn().mockResolvedValue({
    id: 47,
    order_number: "ORD-047",
    status: "preparing",
    items: [],
    address: null,
    customer: {
      id: 1,
      name: "Ali Hassan",
      phone: "+971501234567",
      total_orders: 1,
      total_spend: "44.00",
      first_order_at: null,
      last_order_at: null,
      marketing_opted_in: false,
    },
    rider: null,
    subtotal: "44.00",
    delivery_fee_aed: "0.00",
    total: "44.00",
    created_at: "2026-06-06T09:27:30Z",
    delivered_at: null,
    sla_deadline: null,
    timeline: [],
    chat: [],
    route: [],
  }),
  patchCustomer: vi.fn(),
  patchAddress: vi.fn(),
}));

describe("OrdersScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nf", { status: 404 })));
  });
  afterEach(() => vi.restoreAllMocks());

  it("lists orders from fixtures", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
    expect(screen.getByText("Omar Farouq")).toBeInTheDocument();
  });

  it("opens detail drawer on row click", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => screen.getByText("Ali Hassan"));
    await userEvent.click(screen.getByText("Ali Hassan"));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
  });

  it("filters to empty with a no-match message", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => screen.getByText("Ali Hassan"));
    await userEvent.type(screen.getByPlaceholderText(/search/i), "#9999");
    await waitFor(() => expect(screen.getByText(/no orders match/i)).toBeInTheDocument());
  });
});
