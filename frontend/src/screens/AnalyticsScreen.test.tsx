import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnalyticsScreen } from "./AnalyticsScreen";

describe("AnalyticsScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    // Predictions 404 → null (no data yet). Campaigns 404 → empty [].
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not found", { status: 404 })),
    );
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders without crashing when API returns empty", async () => {
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    // Section headings should be present
    expect(screen.getByText(/demand predictions/i)).toBeInTheDocument();
    expect(screen.getByText(/campaign performance/i)).toBeInTheDocument();
  });

  it("shows 'No predictions yet' when no forecast data available", async () => {
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByTestId("no-predictions")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("no-predictions").textContent).toMatch(
      /no predictions yet/i,
    );
  });

  it("shows campaign empty state when no campaigns returned", async () => {
    // campaigns endpoint returns 200 empty array
    vi.mocked(fetch)
      .mockImplementation((input: unknown) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/marketing/campaigns")) {
          return Promise.resolve(new Response("[]", { status: 200 }));
        }
        // predictions → 404
        return Promise.resolve(new Response("not found", { status: 404 }));
      });

    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByText(/no campaigns yet/i)).toBeInTheDocument(),
    );
  });

  it("renders campaign rows when campaigns are returned", async () => {
    const campaigns = [
      { id: 1, type: "promotional", status: "sent", stats: { sent: 100, converted: 12 } },
      { id: 2, type: "reactivation", status: "draft", stats: { sent: 0, converted: 0 } },
    ];
    vi.mocked(fetch)
      .mockImplementation((input: unknown) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/marketing/campaigns")) {
          return Promise.resolve(
            new Response(JSON.stringify(campaigns), { status: 200 }),
          );
        }
        return Promise.resolve(new Response("not found", { status: 404 }));
      });

    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("#1")).toBeInTheDocument());
    expect(screen.getByText("#2")).toBeInTheDocument();
    // KPI tiles should show totals
    expect(screen.getByText("2")).toBeInTheDocument(); // Total Campaigns
  });

  it("renders forecast tiles when forecast data is returned", async () => {
    const forecast = {
      run_id: 5,
      horizon: "lunch",
      target_date: "2026-06-06",
      predictions: { order_count: 42 },
      adjusted: false,
    };
    vi.mocked(fetch)
      .mockImplementation((input: unknown) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/predictions/latest") && url.includes("lunch")) {
          return Promise.resolve(
            new Response(JSON.stringify(forecast), { status: 200 }),
          );
        }
        if (url.includes("/predictions/latest")) {
          return Promise.resolve(new Response("not found", { status: 404 }));
        }
        if (url.includes("/marketing/campaigns")) {
          return Promise.resolve(new Response("[]", { status: 200 }));
        }
        return Promise.resolve(new Response("not found", { status: 404 }));
      });

    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByText("42 orders")).toBeInTheDocument(),
    );
  });
});
