import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { CheckoutScreen } from "./CheckoutScreen";
import type { OrderDetailOut } from "../lib/types";

const mockDetail: OrderDetailOut = {
  id: 7,
  order_number: "R1-0007",
  status: "ready",
  items: [
    {
      dish_number: 2,
      dish_name: "Mandi",
      qty: 1,
      price_aed: "40.00",
      line_total: "40.00",
    },
  ],
  address: null,
  customer: {
    id: 1,
    name: "Guest",
    phone: "+971501111111",
    total_orders: 1,
    total_spend: "40.00",
    first_order_at: null,
    last_order_at: null,
    marketing_opted_in: false,
  },
  rider: null,
  subtotal: "40.00",
  delivery_fee_aed: "0.00",
  total: "40.00",
  created_at: "2026-07-09T12:00:00Z",
  delivered_at: null,
  sla_deadline: null,
  sla_started_at: null,
  prep_deadline: null,
  cook_estimate_minutes: null,
  timeline: [],
  chat: [],
  route: [],
};

function renderScreen(path = "/orders/7/pay") {
  return renderWithProviders(
    <Routes>
      <Route path="/orders/:id/pay" element={<CheckoutScreen />} />
    </Routes>,
    { initialEntries: [path] },
  );
}

describe("CheckoutScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        const u = String(url);
        const method = (init?.method ?? "GET").toUpperCase();
        if (u.includes("/detail")) {
          return Promise.resolve(
            new Response(JSON.stringify(mockDetail), { status: 200 }),
          );
        }
        if (u.includes("/payments") && method === "GET") {
          return Promise.resolve(
            new Response(
              JSON.stringify({ order_id: 7, total_paid_aed: "0.00", transactions: [] }),
              { status: 200 },
            ),
          );
        }
        if (u.includes("/payments/charge") && method === "POST") {
          return Promise.resolve(
            new Response(
              JSON.stringify({
                id: 99,
                order_id: 7,
                status: "succeeded",
                tender_type: "cash",
                amount_aed: "40.00",
              }),
              { status: 201 },
            ),
          );
        }
        if (u.includes("/staff/approvals") && method === "POST") {
          return Promise.resolve(
            new Response(
              JSON.stringify({ id: 1, action_type: "discount", status: "approved" }),
              { status: 201 },
            ),
          );
        }
        if (u.includes("/discounts") && method === "POST") {
          return Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 201 }));
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders checkout smoke with tender grid, keypad, and amount due", async () => {
    renderScreen();
    expect(await screen.findByTestId("checkout-screen")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/mandi/i)).toBeInTheDocument());
    expect(screen.getByText(/amount due/i)).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /tender grid/i })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: /numeric keypad/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm payment/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^cash$/i })).toBeInTheDocument();
  });

  it("charges cash via payments API on confirm", async () => {
    const user = userEvent.setup();
    renderScreen();
    await screen.findByText(/mandi/i);
    await user.click(screen.getByRole("button", { name: /^cash$/i }));
    await user.click(screen.getByRole("button", { name: /confirm payment/i }));
    await waitFor(() =>
      expect(screen.getByTestId("last-txn")).toHaveTextContent(/succeeded/i),
    );
    const fetchMock = vi.mocked(fetch);
    expect(
      fetchMock.mock.calls.some(
        (c) => String(c[0]).includes("/payments/charge") && (c[1]?.method ?? "GET").toUpperCase() === "POST",
      ),
    ).toBe(true);
  });

  it("shows split mode badge from query", async () => {
    renderScreen("/orders/7/pay?split=1");
    await screen.findByText(/mandi/i);
    expect(screen.getByTestId("split-mode-badge")).toBeInTheDocument();
  });

  it("gates manager discount behind confirm + PIN", async () => {
    const user = userEvent.setup();
    renderScreen();
    await screen.findByText(/mandi/i);
    await user.click(screen.getByRole("button", { name: /apply discount/i }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /continue to pin/i }));
    expect(await screen.findByRole("dialog", { name: /manager approval/i })).toBeInTheDocument();
    expect(screen.getByText(/manager discount override/i)).toBeInTheDocument();
    for (const d of ["1", "2", "3", "4"]) {
      await user.click(screen.getByRole("button", { name: `Digit ${d}` }));
    }
    await user.click(screen.getByRole("button", { name: /approve/i }));
    await waitFor(() =>
      expect(
        vi.mocked(fetch).mock.calls.some(
          (c) => String(c[0]).includes("/discounts") && (c[1]?.method ?? "GET").toUpperCase() === "POST",
        ),
      ).toBe(true),
    );
  });
});
