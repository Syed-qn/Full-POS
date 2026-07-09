import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { PaymentsScreen } from "./PaymentsScreen";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("PaymentsScreen", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: unknown, init?: RequestInit) => {
        const path = String(url);
        if (path.includes("/billing-settings") && init?.method === "PUT") {
          return Promise.resolve(
            json({ service_charge_pct: 10, packaging_charge_aed: 2, min_order_aed: 30 }),
          );
        }
        if (path.includes("/billing-settings")) {
          return Promise.resolve(
            json({ service_charge_pct: 5, packaging_charge_aed: 1, min_order_aed: 25 }),
          );
        }
        if (path.includes("/cash-drawer/sessions/current")) {
          return Promise.resolve(json({ detail: "no open drawer session" }, 404));
        }
        if (path.includes("/cash-drawer/sessions") && init?.method === "POST") {
          return Promise.resolve(
            json(
              {
                id: 1,
                status: "open",
                opening_float_aed: "200.00",
              },
              201,
            ),
          );
        }
        if (path.includes("/payments/links") && init?.method === "POST") {
          return Promise.resolve(
            json(
              {
                id: 9,
                order_id: 3,
                token: "tok_abc",
                amount_aed: "10.00",
                status: "pending",
                expires_at: "2026-07-10T00:00:00Z",
                url: "/api/v1/public/pay/tok_abc",
              },
              201,
            ),
          );
        }
        if (path.includes("/payments/links")) return Promise.resolve(json([]));
        if (path.includes("/gift-cards/issue")) {
          return Promise.resolve(
            json({ id: 1, code: "GIFT01", balance_aed: "50.00", status: "active" }, 201),
          );
        }
        if (path.includes("/gift-cards")) return Promise.resolve(json([]));
        if (path.includes("/reconciliation/report")) {
          return Promise.resolve(
            json({
              gateway_txn_count: 2,
              matched_line_count: 1,
              unmatched_txn_count: 1,
              gateway_total_aed: "30.00",
              matched_total_aed: "20.00",
              unmatched_transactions: [],
            }),
          );
        }
        if (path.includes("/payments/charge")) {
          return Promise.resolve(
            json(
              {
                id: 11,
                status: "succeeded",
                tender_type: "cash",
                amount_aed: "10.00",
                tip_aed: "0.00",
                order_total_paid_aed: "10.00",
              },
              201,
            ),
          );
        }
        if (path.includes("/wallet-session")) {
          return Promise.resolve(json({ session_id: "ws_1", tender_type: "tap_to_pay" }, 201));
        }
        return Promise.resolve(json({}));
      }),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("loads billing settings and recon metrics", async () => {
    renderWithProviders(<PaymentsScreen />);
    await waitFor(() => expect(screen.getByRole("heading", { name: /Payments & billing/i })).toBeInTheDocument());
    expect(await screen.findByText("5")).toBeInTheDocument();
    expect(screen.getByText(/Gateway 2/i)).toBeInTheDocument();
  });

  it("charges an order and opens the cash drawer", async () => {
    renderWithProviders(<PaymentsScreen />);
    await screen.findByRole("heading", { name: /Payments & billing/i });

    fireEvent.change(screen.getByLabelText("Payment order id"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Payment amount"), { target: { value: "10.00" } });
    fireEvent.click(screen.getByRole("button", { name: /^Charge$/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/payments/charge"),
        expect.objectContaining({ method: "POST" }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /open drawer/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/cash-drawer/sessions"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("issues a gift card", async () => {
    renderWithProviders(<PaymentsScreen />);
    await screen.findByRole("heading", { name: /Payments & billing/i });
    fireEvent.click(screen.getByRole("button", { name: /issue card/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/gift-cards/issue"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
