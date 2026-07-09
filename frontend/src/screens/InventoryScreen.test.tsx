import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { InventoryScreen } from "./InventoryScreen";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("InventoryScreen", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: unknown, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith("/api/v1/ingredients") && init?.method === "POST") {
          return Promise.resolve(
            json({
              id: 3,
              name: "Mint",
              unit: "bunch",
              current_stock: "2.000",
              low_stock_threshold: "1.000",
              par_level: "8.000",
              cost_per_unit_aed: "0.5000",
            }, 201),
          );
        }
        if (path.endsWith("/api/v1/ingredients")) {
          return Promise.resolve(
            json([
              {
                id: 1,
                name: "Tomato",
                unit: "kg",
                current_stock: "5.000",
                low_stock_threshold: "2.000",
                par_level: "10.000",
                cost_per_unit_aed: "3.0000",
              },
              {
                id: 2,
                name: "Cheese",
                unit: "kg",
                current_stock: "1.000",
                low_stock_threshold: "2.000",
                par_level: "6.000",
                cost_per_unit_aed: "12.0000",
              },
            ]),
          );
        }
        if (path.includes("/inventory-valuation")) {
          return Promise.resolve(
            json({
              total_value_aed: "27.00",
              rows: [
                {
                  ingredient_id: 1,
                  ingredient_name: "Tomato",
                  unit: "kg",
                  current_stock: "5.000",
                  cost_per_unit_aed: "3.0000",
                  value_aed: "15.00",
                },
                {
                  ingredient_id: 2,
                  ingredient_name: "Cheese",
                  unit: "kg",
                  current_stock: "1.000",
                  cost_per_unit_aed: "12.0000",
                  value_aed: "12.00",
                },
              ],
            }),
          );
        }
        if (path.includes("/stock-adjustments/10/approve")) {
          return Promise.resolve(json({ id: 10, status: "approved" }));
        }
        if (path.includes("/stock-adjustments")) {
          return Promise.resolve(
            json([
              {
                id: 10,
                ingredient_id: 2,
                requested_qty: "4.000",
                previous_qty_snapshot: "1.000",
                reason: "closing count",
                status: "pending",
                requested_by: "cashier",
              },
            ]),
          );
        }
        if (path.includes("/low-stock-alert")) return Promise.resolve(json({ enqueued: true }));
        if (path.includes("/low-stock")) {
          return Promise.resolve(
            json([
              {
                id: 2,
                name: "Cheese",
                unit: "kg",
                current_stock: "1.000",
                low_stock_threshold: "2.000",
                par_level: "6.000",
                cost_per_unit_aed: "12.0000",
              },
            ]),
          );
        }
        if (path.includes("/reorder-suggestions")) {
          return Promise.resolve(
            json([
              {
                ingredient_id: 2,
                ingredient_name: "Cheese",
                current_stock: "1.000",
                par_level: "6.000",
                suggested_order_qty: "5.000",
              },
            ]),
          );
        }
        return Promise.resolve(json({}));
      }),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("shows valuation, low stock, and pending adjustment approvals", async () => {
    renderWithProviders(<InventoryScreen />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Inventory" })).toBeInTheDocument());
    expect(await screen.findByText("AED 27.00")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Tomato" })).toBeInTheDocument();
    expect(screen.getByText(/Cheese needs 5.000 kg/i)).toBeInTheDocument();
    expect(screen.getByText(/closing count/i)).toBeInTheDocument();
  });

  it("creates ingredients, approves adjustments, and sends low-stock alerts", async () => {
    renderWithProviders(<InventoryScreen />);

    await screen.findByRole("cell", { name: "Tomato" });
    fireEvent.change(screen.getByLabelText("Ingredient name"), { target: { value: "Mint" } });
    fireEvent.change(screen.getByLabelText("Unit"), { target: { value: "bunch" } });
    fireEvent.click(screen.getByRole("button", { name: /add ingredient/i }));
    await waitFor(() => expect(screen.getByRole("cell", { name: "Mint" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /approve adjustment 10/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/ingredients/stock-adjustments/10/approve"),
        expect.objectContaining({ method: "POST" }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /send whatsapp low-stock alert/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/ingredients/low-stock-alert"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
