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

  it("shows labor hours for a chosen date", async () => {
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (String(url).includes("/labor-hours")) {
        return Promise.resolve(
          new Response(JSON.stringify([{ staff_id: 1, name: "Amina", hours: 7.5 }]), { status: 200 }),
        );
      }
      return Promise.resolve(new Response("[]", { status: 200 }));
    });
    render(<ReportsScreen />);
    fireEvent.click(screen.getByText(/load labor hours/i));
    await waitFor(() => expect(screen.getByText(/Amina/)).toBeInTheDocument());
  });

  it("shows prep time by item", async () => {
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (String(url).includes("/prep-time-by-item")) {
        return Promise.resolve(
          new Response(
            JSON.stringify([{ key: "Biryani", avg_prep_minutes: 12.5, ticket_count: 8 }]),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("[]", { status: 200 }));
    });
    render(<ReportsScreen />);
    fireEvent.click(screen.getByText(/load prep time by item/i));
    await waitFor(() => expect(screen.getByText(/Biryani/)).toBeInTheDocument());
  });

  it("exports item performance CSV via an authenticated fetch, not a bare link", async () => {
    localStorage.setItem("ops_token", "test-token");
    // jsdom doesn't implement these — stub before spying.
    if (!URL.createObjectURL) URL.createObjectURL = () => "";
    if (!URL.revokeObjectURL) URL.revokeObjectURL = () => {};
    const createObjectURLSpy = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:mock-url");
    const revokeObjectURLSpy = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    vi.mocked(fetch).mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes("/item-performance.csv")) {
        const headers = init?.headers as Record<string, string> | undefined;
        expect(headers?.Authorization).toBe("Bearer test-token");
        return Promise.resolve(new Response("dish,orders\nBiryani,5", { status: 200 }));
      }
      return Promise.resolve(new Response("[]", { status: 200 }));
    });

    render(<ReportsScreen />);
    // Plain anchor with href would always 401 (no cookie auth) — must not exist.
    expect(screen.queryByRole("link", { name: /export csv/i })).not.toBeInTheDocument();

    const exportButton = await screen.findByRole("button", { name: /export csv/i });
    fireEvent.click(exportButton);

    await waitFor(() => expect(createObjectURLSpy).toHaveBeenCalled());
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURLSpy).toHaveBeenCalledWith("blob:mock-url");

    localStorage.removeItem("ops_token");
  });

  it("shows a loading indicator while the initial reload is in flight, then hides it", async () => {
    render(<ReportsScreen />);
    expect(screen.getByText(/loading reports/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/loading reports/i)).not.toBeInTheDocument());
  });

  it("shows an empty-state message when the sales rollup and item performance have no rows", async () => {
    vi.mocked(fetch).mockImplementation(() => Promise.resolve(new Response("[]", { status: 200 })));
    render(<ReportsScreen />);
    await waitFor(() => expect(screen.queryByText(/loading reports/i)).not.toBeInTheDocument());
    expect(screen.getAllByText(/no data for this range/i).length).toBeGreaterThanOrEqual(2);
  });

  it("shows an empty-state message for retention when the load returns no data", async () => {
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (String(url).includes("/retention")) {
        return Promise.resolve(new Response("null", { status: 200 }));
      }
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
      return Promise.resolve(new Response("[]", { status: 200 }));
    });
    render(<ReportsScreen />);
    await waitFor(() => expect(screen.queryByText(/loading reports/i)).not.toBeInTheDocument());
    fireEvent.click(screen.getByText(/load retention/i));
    await waitFor(() => expect(screen.getByText(/no data for this range/i)).toBeInTheDocument());
  });

  it("shows prep time by staff", async () => {
    vi.mocked(fetch).mockImplementation((url: string) => {
      if (String(url).includes("/prep-time-by-staff")) {
        return Promise.resolve(
          new Response(
            JSON.stringify([{ key: "Grill Station", avg_prep_minutes: 9.1, ticket_count: 20 }]),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("[]", { status: 200 }));
    });
    render(<ReportsScreen />);
    fireEvent.click(screen.getByText(/load prep time by staff/i));
    await waitFor(() => expect(screen.getByText(/Grill Station/)).toBeInTheDocument());
  });
});
