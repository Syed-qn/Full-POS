import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { InventoryScreen } from "./InventoryScreen";

vi.mock("../lib/liveEvents", () => ({ subscribeLive: () => () => {} }));

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const REPORT = {
  start: "2026-07-23",
  end: "2026-07-29",
  rows: [
    {
      ingredient_id: 2,
      ingredient_name: "Saffron",
      unit: "kg",
      opening_qty: "5.000",
      purchased_qty: "0.000",
      closing_qty: "3.000",
      actual_qty: "2.000",
      theoretical_qty: "0.000",
      variance_qty: "2.000",
      variance_value_aed: "600.00",
      theoretical_cost_aed: "0.00",
      actual_cost_aed: "600.00",
    },
    {
      ingredient_id: 1,
      ingredient_name: "Chicken",
      unit: "kg",
      opening_qty: "30.000",
      purchased_qty: "0.000",
      closing_qty: "16.000",
      actual_qty: "14.000",
      theoretical_qty: "10.000",
      variance_qty: "4.000",
      variance_value_aed: "80.00",
      theoretical_cost_aed: "200.00",
      actual_cost_aed: "280.00",
    },
  ],
  missing_counts: [] as string[],
  complete: true,
  sales_aed: "8000.00",
  theoretical_cost_aed: "200.00",
  actual_cost_aed: "880.00",
  variance_value_aed: "680.00",
  variance_pct_of_sales: "8.50",
};

function mockApi(report: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: unknown) => {
      const path = String(url);
      if (path.includes("/actual-vs-theoretical")) return Promise.resolve(json(report));
      if (path.includes("/inventory-valuation")) {
        return Promise.resolve(json({ total_value_aed: "0.00", rows: [] }));
      }
      return Promise.resolve(json([]));
    }),
  );
}

describe("InventoryScreen — food cost variance", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
  });

  it("shows the money both ways and the share of sales", async () => {
    mockApi(REPORT);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /^counts/i }));

    await screen.findByText(/food cost variance/i);
    expect(screen.getByText("AED 200.00")).toBeTruthy();
    expect(screen.getByText("AED 880.00")).toBeTruthy();
    // The share of sales is the comparable figure, not the raw dirhams.
    expect(screen.getByText("8.5%")).toBeTruthy();
    // 8.5% is over the 5% line, so it must say so rather than leave the
    // operator to know the threshold.
    expect(screen.getByText(/systematic, not bad luck/i)).toBeTruthy();
  });

  it("lists the worst ingredient by money first, not by quantity", async () => {
    mockApi(REPORT);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /^counts/i }));

    const saffron = await screen.findByText(/Saffron/);
    const chicken = screen.getByText(/Chicken: 4.000 kg/);
    // Saffron moved 2 kg and Chicken 4, so quantity order would flip these.
    // Money order is the point: 600 dirhams beats 80.
    expect(saffron.compareDocumentPosition(chicken) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("names what it could not include instead of quietly dropping it", async () => {
    mockApi({
      ...REPORT,
      rows: [],
      complete: false,
      missing_counts: ["Chicken", "Rice"],
      variance_pct_of_sales: null,
    });
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /^counts/i }));

    // Guessing at an uncounted item would report its whole closing stock as a
    // variance and send someone hunting a theft that never happened.
    await screen.findByText(/not counted, so left out: chicken, rice/i);
    expect(screen.queryByText("8.5%")).toBeNull();
  });

  it("stays off the screen when the report cannot be produced", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: unknown) => {
        const path = String(url);
        if (path.includes("/actual-vs-theoretical")) return Promise.resolve(json({}, 500));
        if (path.includes("/inventory-valuation")) {
          return Promise.resolve(json({ total_value_aed: "0.00", rows: [] }));
        }
        return Promise.resolve(json([]));
      }),
    );
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /^counts/i }));

    // Positive control: the tab itself rendered, so the missing card is a
    // deliberate hide and not a screen that failed to load. Zeros here would
    // read as a perfect kitchen.
    await screen.findByText(/count variance/i);
    expect(screen.queryByText(/food cost variance/i)).toBeNull();
  });
});
