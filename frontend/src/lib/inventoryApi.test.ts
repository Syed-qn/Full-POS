import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  approveStockAdjustment,
  createIngredient,
  createPurchaseOrder,
  createStockAdjustment,
  createVendor,
  getDailyStockClosing,
  getInventoryValuation,
  getReorderSuggestions,
  getVendorPriceComparison,
  listIngredients,
  listLowStock,
  listStockAdjustments,
  receivePurchaseOrder,
  restockIngredient,
  sendLowStockAlert,
  wasteIngredient,
} from "./inventoryApi";

function respondJson(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function bodyOf(init: RequestInit | undefined): unknown {
  return JSON.parse(String(init?.body));
}

describe("inventoryApi", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
    fetchMock = vi.fn().mockImplementation(() => respondJson({}));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.restoreAllMocks());

  it("lists and creates ingredients with the restaurant token", async () => {
    fetchMock
      .mockResolvedValueOnce(respondJson([{ id: 1, name: "Tomato", unit: "kg" }]))
      .mockResolvedValueOnce(respondJson({ id: 2, name: "Mint", unit: "bunch" }, 201));

    await listIngredients();
    await createIngredient({
      name: "Mint",
      unit: "bunch",
      current_stock: "0.000",
      low_stock_threshold: "2.000",
      par_level: "10.000",
      cost_per_unit_aed: "0.5000",
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/ingredients");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("GET");
    expect(fetchMock.mock.calls[0][1]?.headers).toMatchObject({
      Authorization: "Bearer restaurant-token",
    });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/ingredients");
    expect(fetchMock.mock.calls[1][1]?.method).toBe("POST");
    expect(bodyOf(fetchMock.mock.calls[1][1])).toMatchObject({
      name: "Mint",
      unit: "bunch",
    });
  });

  it("posts restock, waste, and stock adjustment requests to the approved ingredient paths", async () => {
    await restockIngredient(7, { quantity: "5.000" });
    await wasteIngredient(7, { quantity: "1.000", reason: "spoilage" });
    await createStockAdjustment(7, {
      requested_qty: "8.000",
      reason: "closing count",
      requested_by: "cashier",
    });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/ingredients/7/restock");
    expect(bodyOf(fetchMock.mock.calls[0][1])).toEqual({ quantity: "5.000" });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/ingredients/7/waste");
    expect(bodyOf(fetchMock.mock.calls[1][1])).toEqual({ quantity: "1.000", reason: "spoilage" });
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/ingredients/7/stock-adjustments");
    expect(bodyOf(fetchMock.mock.calls[2][1])).toMatchObject({ requested_qty: "8.000" });
  });

  it("lists, approves, and rejects stock adjustments", async () => {
    await listStockAdjustments("pending");
    await approveStockAdjustment(22);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/ingredients/stock-adjustments?status=pending");
    expect(fetchMock.mock.calls[0][1]?.method).toBe("GET");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/ingredients/stock-adjustments/22/approve");
    expect(fetchMock.mock.calls[1][1]?.method).toBe("POST");
  });

  it("reads valuation, low-stock, reorder, vendor comparison, and daily closing reports", async () => {
    await getVendorPriceComparison(3);
    await getInventoryValuation();
    await sendLowStockAlert();
    await listLowStock();
    await getReorderSuggestions();
    await getDailyStockClosing("2026-07-09");

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "/api/v1/ingredients/3/vendor-price-comparison",
      "/api/v1/reports/inventory-valuation",
      "/api/v1/ingredients/low-stock-alert",
      "/api/v1/ingredients/low-stock",
      "/api/v1/ingredients/reorder-suggestions",
      "/api/v1/reports/daily-stock-closing?target_date=2026-07-09",
    ]);
  });

  it("creates vendors and purchase orders, then receives a purchase order", async () => {
    await createVendor({ name: "Fresh One", phone: "+971500000001", email: "fresh@example.com" });
    await createPurchaseOrder({
      vendor_id: 11,
      lines: [{ ingredient_id: 3, qty_ordered: "2.000", unit_cost_aed: "7.5000" }],
    });
    await receivePurchaseOrder(33);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/vendors");
    expect(bodyOf(fetchMock.mock.calls[0][1])).toMatchObject({ name: "Fresh One" });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/purchase-orders");
    expect(bodyOf(fetchMock.mock.calls[1][1])).toMatchObject({ vendor_id: 11 });
    expect(fetchMock.mock.calls[2][0]).toBe("/api/v1/purchase-orders/33/receive");
  });
});
