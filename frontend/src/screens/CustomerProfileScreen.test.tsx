import { screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Route, Routes } from "react-router-dom";
import { renderWithProviders } from "../test/render";
import { CustomerProfileScreen } from "./CustomerProfileScreen";
import type { CustomerProfileOut } from "../lib/types";

vi.mock("../lib/customerApi");

// Import mocked modules so we can set resolved values
import * as customerApi from "../lib/customerApi";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const mockProfile: CustomerProfileOut = {
  id: 1,
  name: "Khalid Hassan",
  phone: "+971503334444",
  total_orders: 3,
  total_spend: "99.00",
  first_order_at: "2026-01-01T10:00:00Z",
  last_order_at: "2026-06-10T10:00:00Z",
  usual_order_time: "Evenings (~8:00 PM)",
  marketing_opted_in: true,
  tags: {},
  addresses: [
    {
      id: 1,
      room_apartment: "Villa 5",
      building: "Palm Residences",
      receiver_name: "Khalid Hassan",
      additional_details: null,
      latitude: null,
      longitude: null,
    },
  ],
  recent_orders: [
    {
      id: 10,
      order_number: "R1-0010",
      status: "delivered",
      total: "33.00",
      created_at: "2026-06-01T10:00:00Z",
    },
  ],
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderProfile() {
  return renderWithProviders(
    <Routes>
      <Route path="/customers/:id" element={<CustomerProfileScreen />} />
    </Routes>,
    { initialEntries: ["/customers/1"] },
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("CustomerProfileScreen", () => {
  beforeEach(() => {
    vi.mocked(customerApi.getCustomerProfile).mockResolvedValue(mockProfile);
  });

  // 1. Renders customer name after load
  it("renders customer name after data loads", async () => {
    renderProfile();
    await waitFor(() =>
      expect(screen.getByText("Khalid Hassan")).toBeInTheDocument(),
    );
  });

  // 2. Shows address building name
  it("shows address building name", async () => {
    renderProfile();
    await waitFor(() =>
      expect(screen.getByText(/Palm Residences/i)).toBeInTheDocument(),
    );
  });

  // 3. Shows recent order number
  it("shows recent order number in orders table", async () => {
    renderProfile();
    await waitFor(() =>
      expect(screen.getByText("R1-0010")).toBeInTheDocument(),
    );
  });

  // 4. Shows marketing opt-in toggle state
  it("shows the marketing switch as on when marketing_opted_in is true", async () => {
    renderProfile();
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: /marketing/i })).toHaveAttribute(
        "aria-checked",
        "true",
      ),
    );
  });

  // 5. Save button disabled when no changes made
  it("Save button is disabled when form has not been changed", async () => {
    renderProfile();
    await waitFor(() => screen.getByText("Khalid Hassan"));

    const saveBtn = screen.getByRole("button", { name: /save/i });
    expect(saveBtn).toBeDisabled();
  });

  // 6. Save button enabled after editing name field
  it("Save button becomes enabled after editing the name field", async () => {
    renderProfile();
    await waitFor(() => screen.getByText("Khalid Hassan"));

    const nameInput = screen.getByDisplayValue("Khalid Hassan");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "Khalid Hassan Jr");

    const saveBtn = screen.getByRole("button", { name: /save/i });
    expect(saveBtn).not.toBeDisabled();
  });

  // 7. Stats section shows total orders count
  it("shows correct total orders in stats section", async () => {
    renderProfile();
    await waitFor(() => screen.getByText("Khalid Hassan"));

    // "3" appears in more than one stat cell, so assert at least one.
    expect(screen.getAllByText("3").length).toBeGreaterThanOrEqual(1);
  });

  // 8. Stats section shows total spend
  it("shows total spend in stats section", async () => {
    renderProfile();
    await waitFor(() => screen.getByText("Khalid Hassan"));

    expect(screen.getAllByText("AED 99.00").length).toBeGreaterThanOrEqual(1);
  });

  // 9. Marketing toggle can be flipped, enabling save
  it("Save button becomes enabled after toggling marketing opt-in", async () => {
    renderProfile();
    await waitFor(() => screen.getByText("Khalid Hassan"));

    const toggleBtn = screen.getByRole("switch", { name: /marketing/i });
    fireEvent.click(toggleBtn);

    const saveBtn = screen.getByRole("button", { name: /save/i });
    expect(saveBtn).not.toBeDisabled();
  });

  // 10. Address section shows receiver name
  it("shows address receiver name", async () => {
    renderProfile();
    await waitFor(() => screen.getByText(/Receiver: Khalid Hassan/i));
    expect(screen.getByText(/Receiver: Khalid Hassan/i)).toBeInTheDocument();
  });
});
