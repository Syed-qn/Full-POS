import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnalyticsScreen } from "./AnalyticsScreen";

const fixtureOrders = [
  {
    id: 1,
    customer_name: "Ali",
    customer_phone: "+971500000001",
    status: "delivered",
    total_aed: "50.00",
    items: [],
    created_at: "2026-07-03T10:00:00Z",
    sla_started_at: null,
  },
];

describe("AnalyticsScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-07-03T12:00:00Z"));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("not found", { status: 404 })),
    );
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  function mockFetch() {
    vi.mocked(fetch).mockImplementation((input: unknown) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/marketing/campaigns"))
        return Promise.resolve(new Response("[]", { status: 200 }));
      if (url.includes("/api/v1/orders"))
        return Promise.resolve(new Response(JSON.stringify(fixtureOrders), { status: 200 }));
      if (url.includes("/api/v1/dispatch/kpis"))
        return Promise.resolve(
          new Response(
            JSON.stringify({
              batch_rate_pct: 40,
              avg_stops: 2,
              engine_fallback_pct: 5,
              window: "24h",
            }),
            { status: 200 },
          ),
        );
      return Promise.resolve(new Response("not found", { status: 404 }));
    });
  }

  it("renders delivery, sales trend, and marketing sections", async () => {
    mockFetch();
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByText(/delivery & operations/i)).toBeInTheDocument();
    expect(screen.getByText(/sales trend/i)).toBeInTheDocument();
    expect(screen.getByText(/marketing messages/i)).toBeInTheDocument();
  });

  it("toggles the sales-trend metric between revenue and orders", async () => {
    mockFetch();
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    // Default is revenue.
    expect(screen.getByText(/revenue per day/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Orders" }));
    await waitFor(() =>
      expect(screen.getByText(/orders per day/i)).toBeInTheDocument(),
    );
  });

  it("shows delivery KPIs and dispatch panel when orders load", async () => {
    mockFetch();
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText(/batch rate/i)).toBeInTheDocument());
    expect(screen.getByText("Revenue collected")).toBeInTheDocument();
    expect(screen.getByText("AED 50")).toBeInTheDocument();
    expect(screen.getByText("Completion rate")).toBeInTheDocument();
  });

  it("shows campaign empty state when no campaigns in range", async () => {
    mockFetch();
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByText(/no campaigns in this period/i)).toBeInTheDocument(),
    );
  });

  it("counts only sent campaigns in the summary strip", async () => {
    const campaigns = [
      {
        id: 1,
        type: "promotional",
        status: "sent",
        stats: { sent: 100, converted: 13 },
        created_at: "2026-07-03T10:00:00Z",
      },
      {
        id: 2,
        type: "reactivation",
        status: "draft",
        stats: { sent: 0, converted: 0 },
        created_at: "2026-07-03T11:00:00Z",
      },
    ];
    vi.mocked(fetch).mockImplementation((input: unknown) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/marketing/campaigns"))
        return Promise.resolve(new Response(JSON.stringify(campaigns), { status: 200 }));
      if (url.includes("/api/v1/orders"))
        return Promise.resolve(new Response(JSON.stringify(fixtureOrders), { status: 200 }));
      if (url.includes("/api/v1/dispatch/kpis"))
        return Promise.resolve(
          new Response(
            JSON.stringify({ batch_rate_pct: 40, avg_stops: 2, engine_fallback_pct: 0 }),
            { status: 200 },
          ),
        );
      return Promise.resolve(new Response("not found", { status: 404 }));
    });
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Messages delivered")).toBeInTheDocument());
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("13")).toBeInTheDocument();
    const campaignsSentLabel = screen.getByText("Campaigns sent");
    expect(campaignsSentLabel.previousElementSibling?.textContent).toBe("1");
  });

  it("changes period label when date preset is selected", async () => {
    mockFetch();
    render(<AnalyticsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: "All time" }));
    await waitFor(() =>
      expect(screen.getByText(/promotion results for all time/i)).toBeInTheDocument(),
    );
  });
});