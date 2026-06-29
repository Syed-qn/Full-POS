import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatCustomerPanel } from "./ChatCustomerPanel";

const ctx = {
  customer_id: 9,
  name: "Aisha",
  phone: "+97155500011",
  wallet_balance_aed: "25.00",
  wallet_available_aed: "25.00",
  wallet_status: "active",
  recent_orders: [
    { id: 1, order_number: "R1-0001", status: "delivered", total_aed: "40.00", created_at: "2026-06-28T10:00:00Z" },
  ],
};

describe("ChatCustomerPanel", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() =>
        Promise.resolve(new Response(JSON.stringify(ctx), { status: 200 })),
      ),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows the customer name + wallet balance", async () => {
    render(<ChatCustomerPanel conversationId={1} />);
    await waitFor(() => expect(screen.getByText(/Aisha · Wallet AED 25.00/)).toBeInTheDocument());
  });

  it("reveals orders + actions when expanded", async () => {
    render(<ChatCustomerPanel conversationId={1} />);
    await waitFor(() => screen.getByText(/Aisha/));
    fireEvent.click(screen.getByRole("button", { name: /actions/i }));
    expect(screen.getByText("R1-0001")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^issue$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^credit$/i })).toBeInTheDocument();
  });

  it("issue button disabled until amount entered", async () => {
    render(<ChatCustomerPanel conversationId={1} />);
    await waitFor(() => screen.getByText(/Aisha/));
    fireEvent.click(screen.getByRole("button", { name: /actions/i }));
    const issue = screen.getByRole("button", { name: /^issue$/i });
    expect(issue).toBeDisabled();
    fireEvent.change(screen.getByLabelText("coupon amount"), { target: { value: "10" } });
    expect(issue).not.toBeDisabled();
  });
});
