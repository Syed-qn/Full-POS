import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  it("shows the loading skeleton before the first fetch resolves", () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    // Still loading on first paint → skeleton, not data or the empty state.
    expect(screen.getByLabelText("Loading rows")).toBeInTheDocument();
    expect(screen.queryByText("Ali Hassan")).not.toBeInTheDocument();
    expect(screen.queryByText(/no orders match/i)).not.toBeInTheDocument();
  });

  it("lists orders from fixtures", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
    expect(screen.getByText("Omar Farouq")).toBeInTheDocument();
    // Skeleton is gone once data has loaded.
    expect(screen.queryByLabelText("Loading rows")).not.toBeInTheDocument();
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

  it("filters by a custom From–To date range (fixtures are 2026-06-06)", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => screen.getByText("Ali Hassan"));

    // From the next day → all fixtures fall before the range → empty.
    fireEvent.change(screen.getByLabelText(/from date/i), { target: { value: "2026-06-07" } });
    await waitFor(() => expect(screen.getByText(/no orders match/i)).toBeInTheDocument());

    // Widen From to the order day → they reappear.
    fireEvent.change(screen.getByLabelText(/from date/i), { target: { value: "2026-06-06" } });
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());

    // A To before the order day → empty again (upper bound).
    fireEvent.change(screen.getByLabelText(/to date/i), { target: { value: "2026-06-05" } });
    await waitFor(() => expect(screen.getByText(/no orders match/i)).toBeInTheDocument());

    // Clear dates → everything back.
    await userEvent.click(screen.getByRole("button", { name: /clear dates/i }));
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
  });

  it("filters orders by status", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => screen.getByText("Ali Hassan"));

    // Only the 'preparing' order (Ali Hassan) survives.
    await userEvent.selectOptions(screen.getByLabelText(/filter by status/i), "preparing");
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
    expect(screen.queryByText("Omar Farouq")).not.toBeInTheDocument();
    expect(screen.queryByText("Sara Khan")).not.toBeInTheDocument();

    // A status no fixture has → empty.
    await userEvent.selectOptions(screen.getByLabelText(/filter by status/i), "delivered");
    await waitFor(() => expect(screen.getByText(/no orders match/i)).toBeInTheDocument());

    // Back to all statuses → everything returns.
    await userEvent.selectOptions(screen.getByLabelText(/filter by status/i), "all");
    await waitFor(() => expect(screen.getByText("Omar Farouq")).toBeInTheDocument());
  });

  it("the Today preset excludes older orders", async () => {
    render(<MemoryRouter><OrdersScreen /></MemoryRouter>);
    await waitFor(() => screen.getByText("Ali Hassan"));
    // Test runs well after 2026-06-06, so 'Today' filters the fixtures out.
    await userEvent.click(screen.getByRole("button", { name: "Today" }));
    await waitFor(() => expect(screen.getByText(/no orders match/i)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "All" }));
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
  });
});
