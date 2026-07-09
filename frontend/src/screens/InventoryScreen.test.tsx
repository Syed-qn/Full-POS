import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
            json(
              {
                id: 3,
                name: "Mint",
                unit: "bunch",
                current_stock: "2.000",
                low_stock_threshold: "1.000",
                par_level: "8.000",
                cost_per_unit_aed: "0.5000",
              },
              201,
            ),
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
        if (path.includes("/reports/variance")) return Promise.resolve(json([]));
        if (path.includes("/reports/anomaly-alerts")) return Promise.resolve(json([]));
        if (path.includes("/reports/spoilage")) return Promise.resolve(json([]));
        if (path.includes("/reports/closing-snapshot")) return Promise.resolve(json([]));
        if (path.includes("/locations")) {
          return Promise.resolve(
            json([
              { id: 1, name: "Main branch", code: "branch", kitchen_role: "branch", is_active: true },
              { id: 2, name: "Central kitchen", code: "central", kitchen_role: "central", is_active: true },
              { id: 3, name: "Commissary", code: "commissary", kitchen_role: "commissary", is_active: true },
            ]),
          );
        }
        if (path.includes("/expiring-soon")) return Promise.resolve(json([]));
        if (path.endsWith("/api/v1/vendors") && init?.method === "POST") {
          return Promise.resolve(json({ id: 9, name: "Fresh Co", phone: "+9715000999" }, 201));
        }
        if (path.includes("/api/v1/vendors")) {
          return Promise.resolve(json([{ id: 5, name: "Spice Co", phone: "+9715000001" }]));
        }
        if (path.includes("/purchase-orders") && init?.method === "POST") {
          return Promise.resolve(
            json(
              {
                id: 40,
                vendor_id: 5,
                status: "draft",
                lines: [{ id: 1, ingredient_id: 1, qty_ordered: "5.000", unit_cost_aed: "1.0000" }],
              },
              201,
            ),
          );
        }
        if (path.includes("/purchase-orders") && path.includes("/receive")) {
          return Promise.resolve(json({ id: 40, vendor_id: 5, status: "received", lines: [] }));
        }
        if (path.includes("/purchase-orders")) {
          return Promise.resolve(
            json([
              {
                id: 40,
                vendor_id: 5,
                status: "draft",
                lines: [{ id: 1, ingredient_id: 1, qty_ordered: "5.000", unit_cost_aed: "1.0000" }],
              },
            ]),
          );
        }
        if (path.includes("/api/v1/grn")) return Promise.resolve(json([]));
        if (path.includes("/waste")) {
          return Promise.resolve(
            json({
              id: 1,
              name: "Tomato",
              unit: "kg",
              current_stock: "4.000",
              low_stock_threshold: "2.000",
              par_level: "10.000",
              cost_per_unit_aed: "3.0000",
            }),
          );
        }
        if (path.includes("/restock")) {
          return Promise.resolve(
            json({
              id: 1,
              name: "Tomato",
              unit: "kg",
              current_stock: "6.000",
              low_stock_threshold: "2.000",
              par_level: "10.000",
              cost_per_unit_aed: "3.0000",
            }),
          );
        }
        if (path.includes("/stock-count")) {
          return Promise.resolve(
            json({
              variance: "-1.000",
              previous_stock: "5.000",
              counted_stock: "4.000",
              variance_pct: 20,
            }),
          );
        }
        if (path.includes("/batches")) {
          return Promise.resolve(
            json({
              id: 99,
              ingredient_id: 1,
              qty: "2.000",
              qty_remaining: "2.000",
              expiry_date: "2026-08-01",
              received_at: "2026-07-09T00:00:00Z",
            }, 201),
          );
        }
        if (path.includes("/staff/approvals") && init?.method === "POST") {
          return Promise.resolve(
            json({ id: 1, action_type: "stock_adjustment", status: "approved" }, 201),
          );
        }
        return Promise.resolve(json([]));
      }),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("shows valuation, low stock, locations, and pending adjustment approvals", async () => {
    renderWithProviders(<InventoryScreen />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Inventory" })).toBeInTheDocument());
    expect(await screen.findByText("AED 27.00")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Tomato" })).toBeInTheDocument();
    expect(screen.getByText(/Cheese needs 5.000 kg/i)).toBeInTheDocument();
    expect(screen.getByText(/closing count/i)).toBeInTheDocument();
    expect(screen.getByText(/Central kitchen/i)).toBeInTheDocument();
    expect(screen.getByText(/Vendor: Spice Co/i)).toBeInTheDocument();
  });

  it("creates ingredients, approves adjustments, and sends low-stock alerts", async () => {
    renderWithProviders(<InventoryScreen />);

    await screen.findByRole("cell", { name: "Tomato" });
    fireEvent.change(screen.getByLabelText("Ingredient name"), { target: { value: "Mint" } });
    fireEvent.change(screen.getByLabelText("Unit"), { target: { value: "bunch" } });
    fireEvent.click(screen.getByRole("button", { name: /add ingredient/i }));
    await waitFor(() => expect(screen.getByRole("cell", { name: "Mint" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /approve adjustment 10/i }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /continue to pin/i }));
    const pinDialog = await screen.findByRole("dialog", { name: /manager approval/i });
    for (const d of ["1", "2", "3", "4"]) {
      fireEvent.click(within(pinDialog).getByRole("button", { name: `Digit ${d}` }));
    }
    fireEvent.change(within(pinDialog).getByPlaceholderText(/why is this needed/i), {
      target: { value: "Manager approved variance" },
    });
    fireEvent.click(within(pinDialog).getByRole("button", { name: /^approve$/i }));
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

  it("logs spoilage and creates a vendor/PO from the inventory screen", async () => {
    renderWithProviders(<InventoryScreen />);
    await screen.findByRole("cell", { name: "Tomato" });

    fireEvent.change(screen.getByLabelText("Ops quantity"), { target: { value: "1.000" } });
    fireEvent.change(screen.getByLabelText("Waste reason type"), { target: { value: "spoilage" } });
    fireEvent.click(screen.getByRole("button", { name: /log waste\/spoilage/i }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /continue to pin/i }));
    const wastePin = await screen.findByRole("dialog", { name: /manager approval/i });
    for (const d of ["1", "2", "3", "4"]) {
      fireEvent.click(within(wastePin).getByRole("button", { name: `Digit ${d}` }));
    }
    fireEvent.change(within(wastePin).getByPlaceholderText(/why is this needed/i), {
      target: { value: "Spoilage write-off" },
    });
    fireEvent.click(within(wastePin).getByRole("button", { name: /^approve$/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/ingredients/1/waste"),
        expect.objectContaining({ method: "POST" }),
      ),
    );

    fireEvent.change(screen.getByLabelText("Vendor name"), { target: { value: "Fresh Co" } });
    fireEvent.click(screen.getByRole("button", { name: /add vendor/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/vendors"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
