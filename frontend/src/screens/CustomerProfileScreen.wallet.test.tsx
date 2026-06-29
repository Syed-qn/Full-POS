import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { CustomerProfileScreen } from "./CustomerProfileScreen";

vi.mock("../lib/customerApi");
vi.mock("../lib/walletApi");

import * as customerApi from "../lib/customerApi";
import * as walletApi from "../lib/walletApi";

const profile = {
  id: 5, name: "Wallet Cust", phone: "+97150000000", total_orders: 1, total_spend: "10.00",
  first_order_at: null, last_order_at: null, usual_order_time: null, marketing_opted_in: false,
  tags: {}, addresses: [], recent_orders: [],
};

function renderScreen() {
  return render(
    <MemoryRouter initialEntries={["/customers/5"]}>
      <Routes>
        <Route path="/customers/:id" element={<CustomerProfileScreen />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("CustomerProfileScreen wallet editing", () => {
  beforeEach(() => {
    vi.mocked(customerApi.getCustomerProfile).mockResolvedValue(profile as never);
    vi.mocked(walletApi.getWallet).mockResolvedValue({
      customer_id: 5, balance_aed: "0.00", available_aed: "0.00", status: "active",
    });
    vi.mocked(walletApi.getWalletEntries).mockResolvedValue([]);
    vi.mocked(walletApi.creditWallet).mockResolvedValue({
      customer_id: 5, balance_aed: "20.00", available_aed: "20.00", status: "active",
    });
    vi.mocked(walletApi.debitWallet).mockResolvedValue({
      customer_id: 5, balance_aed: "0.00", available_aed: "0.00", status: "active",
    });
    vi.mocked(customerApi.setCustomerLoyaltyTier).mockResolvedValue(
      { ...profile, loyalty_tier: "gold", loyalty_tier_locked: true } as never,
    );
  });

  it("sets a loyalty tier via the override control", async () => {
    renderScreen();
    await waitFor(() => screen.getByLabelText("set loyalty tier"));
    fireEvent.change(screen.getByLabelText("set loyalty tier"), { target: { value: "gold" } });
    await waitFor(() =>
      expect(vi.mocked(customerApi.setCustomerLoyaltyTier)).toHaveBeenCalledWith(5, { tier: "gold" }),
    );
  });

  it("shows an Add credit control and disables it until an amount is entered", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getByRole("button", { name: /add credit/i })).toBeInTheDocument());
    const btn = screen.getByRole("button", { name: /add credit/i });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByLabelText("credit amount"), { target: { value: "20" } });
    expect(btn).not.toBeDisabled();
  });

  it("credits the wallet on click", async () => {
    renderScreen();
    await waitFor(() => screen.getByLabelText("credit amount"));
    fireEvent.change(screen.getByLabelText("credit amount"), { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText("credit reason"), { target: { value: "goodwill" } });
    fireEvent.click(screen.getByRole("button", { name: /add credit/i }));
    await waitFor(() =>
      expect(vi.mocked(walletApi.creditWallet)).toHaveBeenCalledWith(5, "20", "goodwill"),
    );
  });

  it("deducts from the wallet on Deduct click", async () => {
    renderScreen();
    await waitFor(() => screen.getByLabelText("credit amount"));
    fireEvent.change(screen.getByLabelText("credit amount"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("credit reason"), { target: { value: "correction" } });
    fireEvent.click(screen.getByRole("button", { name: /deduct/i }));
    await waitFor(() =>
      expect(vi.mocked(walletApi.debitWallet)).toHaveBeenCalledWith(5, "5", "correction"),
    );
  });
});
