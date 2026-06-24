import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { CustomersScreen } from "./CustomersScreen";
import type { CustomerListOut } from "../lib/types";

vi.mock("../lib/customerApi");
import * as customerApi from "../lib/customerApi";

const LIST: CustomerListOut = {
  items: [
    { id: 1, name: "Ali Hassan", phone: "+971500000001", total_orders: 3, total_spend: "120.00", first_order_at: null, last_order_at: null, marketing_opted_in: true },
    { id: 2, name: "Sara Khan", phone: "+971500000002", total_orders: 0, total_spend: "0.00", first_order_at: null, last_order_at: null, marketing_opted_in: false },
    { id: 3, name: "Omar Farouq", phone: "+971500000003", total_orders: 1, total_spend: "35.00", first_order_at: null, last_order_at: null, marketing_opted_in: true },
  ],
  limit: 50,
  offset: 0,
};

function renderScreen() {
  return render(<MemoryRouter><CustomersScreen /></MemoryRouter>);
}

describe("CustomersScreen filters", () => {
  beforeEach(() => {
    vi.mocked(customerApi.listCustomers).mockResolvedValue(LIST);
  });

  it("shows the loading skeleton before the first fetch resolves", () => {
    renderScreen();
    // Still loading on first paint → skeleton, not data or the empty state.
    expect(screen.getByLabelText("Loading rows")).toBeInTheDocument();
    expect(screen.queryByText("Ali Hassan")).not.toBeInTheDocument();
    expect(screen.queryByText(/no customers found/i)).not.toBeInTheDocument();
  });

  it("filters by marketing opt-out", async () => {
    renderScreen();
    await waitFor(() => screen.getByText("Ali Hassan"));
    await userEvent.click(screen.getByRole("button", { name: "Opted Out" }));
    await waitFor(() => expect(screen.getByText("Sara Khan")).toBeInTheDocument());
    expect(screen.queryByText("Ali Hassan")).not.toBeInTheDocument();
    expect(screen.queryByText("Omar Farouq")).not.toBeInTheDocument();
  });

  it("filters by repeat customers (2+ orders)", async () => {
    renderScreen();
    await waitFor(() => screen.getByText("Ali Hassan"));
    await userEvent.click(screen.getByRole("button", { name: /repeat/i }));
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
    expect(screen.queryByText("Omar Farouq")).not.toBeInTheDocument(); // 1 order
    expect(screen.queryByText("Sara Khan")).not.toBeInTheDocument(); // 0 orders
  });

  it("filters by no orders", async () => {
    renderScreen();
    await waitFor(() => screen.getByText("Ali Hassan"));
    await userEvent.click(screen.getByRole("button", { name: "No orders" }));
    await waitFor(() => expect(screen.getByText("Sara Khan")).toBeInTheDocument());
    expect(screen.queryByText("Ali Hassan")).not.toBeInTheDocument();
  });

  it("filters by minimum spend", async () => {
    renderScreen();
    await waitFor(() => screen.getByText("Ali Hassan"));
    fireEvent.change(screen.getByLabelText(/minimum spend/i), { target: { value: "100" } });
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument()); // 120
    expect(screen.queryByText("Omar Farouq")).not.toBeInTheDocument(); // 35
    expect(screen.queryByText("Sara Khan")).not.toBeInTheDocument(); // 0
  });
});
