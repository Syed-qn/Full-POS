import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearStaffSession, setStaffSession } from "../lib/navAccess";
import { renderWithProviders } from "../test/render";
import { OrderDetailScreen } from "./OrderDetailScreen";
import type { OrderDetailOut } from "../lib/types";

const mockDetail: OrderDetailOut = {
  id: 42,
  order_number: "R1-0042",
  status: "preparing",
  items: [
    {
      dish_number: 1,
      dish_name: "Chicken Biryani",
      qty: 2,
      price_aed: "28.00",
      line_total: "56.00",
      notes: "extra raita",
    },
  ],
  address: {
    id: 1,
    room_apartment: "12A",
    building: "Marina",
    receiver_name: "Sara",
    additional_details: null,
    latitude: 25.2,
    longitude: 55.2,
  },
  customer: {
    id: 1,
    name: "Sara",
    phone: "+971500000001",
    total_orders: 3,
    total_spend: "100.00",
    first_order_at: null,
    last_order_at: null,
    marketing_opted_in: true,
    allergy_notes: "Peanuts",
  },
  rider: null,
  subtotal: "56.00",
  delivery_fee_aed: "5.00",
  total: "61.00",
  created_at: "2026-07-09T10:00:00Z",
  delivered_at: null,
  sla_deadline: null,
  sla_started_at: "2026-07-09T10:00:00Z",
  prep_deadline: "2026-07-09T10:30:00Z",
  cook_estimate_minutes: 20,
  timeline: [
    {
      ts: "2026-07-09T10:01:00Z",
      action: "order_status_transition",
      actor: "manager",
      after: { status: "confirmed" },
    },
  ],
  chat: [],
  route: [],
};

function renderScreen() {
  return renderWithProviders(
    <Routes>
      <Route path="/orders/:id" element={<OrderDetailScreen />} />
    </Routes>,
    { initialEntries: ["/orders/42"] },
  );
}

describe("OrderDetailScreen", () => {
  beforeEach(() => {
    clearStaffSession();
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        const u = String(url);
        if (u.includes("/detail")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockDetail), { status: 200 }),
          );
        }
        if (u.includes("/payments")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ order_id: 42, total_paid_aed: "0.00", transactions: [] }),
              { status: 200 },
            ),
          );
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      }),
    );
  });
  afterEach(() => {
    clearStaffSession();
    vi.restoreAllMocks();
  });

  it("renders order detail smoke with header, items, timeline", async () => {
    renderScreen();
    expect(await screen.findByTestId("order-detail-screen")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("R1-0042")).toBeInTheDocument());
    expect(screen.getByText(/chicken biryani/i)).toBeInTheDocument();
    expect(screen.getByTestId("allergy-warning")).toHaveTextContent(/peanuts/i);
    expect(screen.getByText(/status → confirmed/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pay/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /mark as ready/i })).toBeInTheDocument();
  });

  it("opens manager PIN path for void from More menu", async () => {
    const user = userEvent.setup();
    renderScreen();
    await screen.findByText("R1-0042");
    await user.click(screen.getByRole("button", { name: /^more$/i }));
    await user.click(screen.getByRole("menuitem", { name: /void order/i }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /continue to pin/i }));
    expect(await screen.findByRole("dialog", { name: /manager approval/i })).toBeInTheDocument();
  });

  it("waiter mode hides Pay and shows Bill at cashier", async () => {
    setStaffSession({ role: "waiter", name: "W1" });
    renderScreen();
    await screen.findByText("R1-0042");
    expect(screen.queryByTestId("order-detail-pay")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /bill at cashier/i })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /mark as ready/i })).not.toBeInTheDocument();
  });

  it("cashier mode keeps primary Pay CTA", async () => {
    setStaffSession({ role: "cashier", name: "C1" });
    renderScreen();
    await screen.findByText("R1-0042");
    expect(screen.getByTestId("order-detail-pay")).toBeInTheDocument();
  });
});
