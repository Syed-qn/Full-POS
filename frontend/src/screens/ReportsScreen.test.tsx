import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReportsScreen } from "./ReportsScreen";

describe("ReportsScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (String(url).includes("/sales-rollup")) {
          return Promise.resolve(
            new Response(JSON.stringify([{ bucket: "2026-07-08", revenue_aed: "500.00", order_count: 10 }]), { status: 200 }),
          );
        }
        if (String(url).includes("/item-performance")) {
          return Promise.resolve(
            new Response(
              JSON.stringify([{ dish_name: "Biryani", order_count: 5, revenue_aed: "100.00", food_cost_aed: "40.00", margin_aed: "60.00", margin_pct: 60 }]),
              { status: 200 },
            ),
          );
        }
        if (String(url).includes("/z-report")) {
          return Promise.resolve(
            new Response(
              JSON.stringify({ gross_sales_aed: "500.00", total_discounts_aed: "0.00", cod_collected_aed: "500.00", drawer_sessions: [] }),
              { status: 200 },
            ),
          );
        }
        return Promise.resolve(new Response("[]", { status: 200 }));
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("loads and shows sales rollup for the default range", async () => {
    render(<ReportsScreen />);
    await waitFor(() => expect(screen.getByText("AED 500.00")).toBeInTheDocument());
  });

  it("shows item performance rows", async () => {
    render(<ReportsScreen />);
    await waitFor(() => expect(screen.getByText("Biryani")).toBeInTheDocument());
  });

  it("loads a Z-report for a chosen date", async () => {
    render(<ReportsScreen />);
    fireEvent.click(screen.getByText(/load z-report/i));
    await waitFor(() => expect(screen.getByText(/gross sales: AED 500.00/i)).toBeInTheDocument());
  });

  it("shows retention metrics", async () => {
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (String(url).includes("/retention")) {
        return Promise.resolve(
          new Response(JSON.stringify({ repeat_rate_pct: 42, new_customers: 3, returning_customers: 7 }), { status: 200 }),
        );
      }
      return Promise.resolve(new Response("[]", { status: 200 }));
    });
    render(<ReportsScreen />);
    fireEvent.click(screen.getByText(/load retention/i));
    await waitFor(() => expect(screen.getByText(/42%/)).toBeInTheDocument());
  });
});
