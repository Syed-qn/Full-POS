import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnalyticsScreen } from "./AnalyticsScreen";

describe("AnalyticsScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
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
    expect(screen.getByText(/expected orders today/i)).toBeInTheDocument();
    expect(screen.getByText(/marketing messages/i)).toBeInTheDocument();
  });

  it("shows 'No predictions yet' when no forecast data available", async () => {
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByText(/no predictions yet/i)).toBeInTheDocument(),
    );
  });

  it("shows campaign empty state when no campaigns returned", async () => {
    vi.mocked(fetch).mockImplementation((input: unknown) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/marketing/campaigns"))
        return Promise.resolve(new Response("[]", { status: 200 }));
      return Promise.resolve(new Response("not found", { status: 404 }));
    });
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByText(/no campaigns yet/i)).toBeInTheDocument(),
    );
  });

  it("renders campaign stats when campaigns are returned", async () => {
    const campaigns = [
      { id: 1, type: "promotional", status: "sent", stats: { sent: 100, converted: 12 } },
      { id: 2, type: "reactivation", status: "draft", stats: { sent: 0, converted: 0 } },
    ];
    vi.mocked(fetch).mockImplementation((input: unknown) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/marketing/campaigns"))
        return Promise.resolve(new Response(JSON.stringify(campaigns), { status: 200 }));
      return Promise.resolve(new Response("not found", { status: 404 }));
    });
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    // 2 campaigns total
    await waitFor(() => expect(screen.getByText("2")).toBeInTheDocument());
    // 100 messages delivered
    expect(screen.getByText("100")).toBeInTheDocument();
  });

  it("renders forecast chart when forecast data is returned", async () => {
    const forecast = {
      run_id: 5, horizon: "lunch", target_date: "2026-06-06",
      predictions: { order_count: 42 }, adjusted: false,
    };
    vi.mocked(fetch).mockImplementation((input: unknown) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/predictions/latest") && url.includes("lunch"))
        return Promise.resolve(new Response(JSON.stringify(forecast), { status: 200 }));
      if (url.includes("/predictions/latest"))
        return Promise.resolve(new Response("not found", { status: 404 }));
      if (url.includes("/marketing/campaigns"))
        return Promise.resolve(new Response("[]", { status: 200 }));
      return Promise.resolve(new Response("not found", { status: 404 }));
    });
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    // Chart renders — no "no predictions" message
    await waitFor(() =>
      expect(screen.queryByText(/no predictions yet/i)).not.toBeInTheDocument(),
    );
  });
});
