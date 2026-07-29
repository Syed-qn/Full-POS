import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { InventoryScreen } from "./InventoryScreen";

vi.mock("../lib/liveEvents", () => ({ subscribeLive: () => () => {} }));

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

/** Seven counts, so the list pages 5 then 2. */
const VARIANCE = Array.from({ length: 7 }, (_, i) => ({
  id: i + 1,
  ingredient_id: 1,
  ingredient_name: `Item${i}`,
  previous_stock: "30.000",
  counted_stock: "28.000",
  variance: "-2.000",
  counted_by: "manager",
  reason_code: null,
  reason: null,
  variance_value_aed: "-40.00",
  reviewed: false,
  created_at: "2026-07-29T06:00:00",
}));

/** Seven days of closings, each worth 100 less than the day before it, so
 *  every row except the oldest has a comparison to draw. */
const CLOSINGS = Array.from({ length: 7 }, (_, i) => ({
  closing_date: `2026-07-${29 - i}`,
  total_value_aed: String(1000 - i * 100),
  items: 2,
}));

function mockApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: unknown) => {
      const path = String(url);
      if (path.includes("/reports/variance")) return Promise.resolve(json(VARIANCE));
      if (path.includes("/reports/closing-history")) return Promise.resolve(json(CLOSINGS));
      if (path.includes("/inventory-valuation")) {
        return Promise.resolve(json({ total_value_aed: "0.00", rows: [] }));
      }
      if (path.includes("/actual-vs-theoretical")) return Promise.resolve(json({}, 500));
      return Promise.resolve(json([]));
    }),
  );
}

describe("InventoryScreen — paging the count lists", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
    mockApi();
  });

  it("pages count variance five at a time", async () => {
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /^counts/i }));

    // Both cards page identically, so the range text appears twice — the item
    // names are what identify THIS list.
    await screen.findByText(/Item0/);
    expect(screen.queryByText(/Item5/)).toBeNull();
    expect(screen.getAllByText(/1–5 of 7/)).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: /next page of count variance/i }));
    await screen.findByText(/Item5/);
    expect(screen.queryByText(/Item0/)).toBeNull();
    // Only the variance card moved; the closing history stayed where it was.
    expect(screen.getByText(/6–7 of 7/)).toBeTruthy();
    expect(screen.getByText(/1–5 of 7/)).toBeTruthy();
  });

  it("keeps the day-over-day change correct across a page boundary", async () => {
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /^counts/i }));

    // Row 5 (AED 600) is the LAST on page one and its comparison lives on page
    // two (AED 500). Comparing within the page would leave it reading as no
    // change when the stock actually moved.
    const lastOnPage = await screen.findByText(/AED 600\.00/);
    expect(lastOnPage.textContent).toContain("AED 100.00");
  });

  it("hides a pager when the list fits on one page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: unknown) => {
        const path = String(url);
        if (path.includes("/reports/variance")) {
          return Promise.resolve(json(VARIANCE.slice(0, 3)));
        }
        if (path.includes("/inventory-valuation")) {
          return Promise.resolve(json({ total_value_aed: "0.00", rows: [] }));
        }
        if (path.includes("/actual-vs-theoretical")) return Promise.resolve(json({}, 500));
        return Promise.resolve(json([]));
      }),
    );
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /^counts/i }));

    // Positive control: the card rendered, so the missing pager is "it fits"
    // and not "the list failed to load".
    await screen.findByText(/Item0/);
    expect(screen.queryByRole("button", { name: /next page of count variance/i })).toBeNull();
  });
});
