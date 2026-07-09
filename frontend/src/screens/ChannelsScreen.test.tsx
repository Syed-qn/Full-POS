import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChannelsScreen } from "./ChannelsScreen";

vi.mock("../lib/channelsApi", () => ({
  fetchChannels: vi.fn(),
  fetchChannelInbox: vi.fn(),
  fetchCommissionReport: vi.fn(),
  fetchProfitReport: vi.fn(),
  fetchReconciliation: vi.fn(),
  pauseChannel: vi.fn(),
  resumeChannel: vi.fn(),
  updateChannels: vi.fn(),
  ensurePublicSlug: vi.fn(),
  syncMenu: vi.fn(),
  syncPrice: vi.fn(),
  syncStock: vi.fn(),
  createSettlement: vi.fn(),
}));

import * as api from "../lib/channelsApi";

const mockChannels = {
  channels: {
    talabat: {
      enabled: true,
      accepting: true,
      commission_pct: 25,
      mode: "mock",
    },
    website: {
      enabled: true,
      accepting: true,
      commission_pct: 0,
      mode: "mock",
    },
  },
  providers: ["talabat", "deliveroo", "careem", "ubereats", "noon", "zomato"],
  public_slug: "demo-cafe",
  order_links: {
    website: "http://localhost/order/demo-cafe",
    mobile_app: "http://localhost/order/demo-cafe?channel=mobile_app",
    instagram: "http://localhost/order/demo-cafe?channel=instagram",
    google_business: "http://localhost/order/demo-cafe?channel=google_business",
    kiosk: "http://localhost/order/demo-cafe?channel=kiosk",
    slug: "demo-cafe",
  },
};

describe("ChannelsScreen", () => {
  beforeEach(() => {
    vi.mocked(api.fetchChannels).mockResolvedValue(mockChannels as never);
    vi.mocked(api.fetchChannelInbox).mockResolvedValue({
      orders: [
        {
          id: 1,
          order_number: "TB-1",
          status: "confirmed",
          total_aed: "20.00",
          source_channel: "talabat",
          order_type: "aggregator",
          created_at: "2026-07-09T10:00:00",
        },
      ],
    });
    vi.mocked(api.fetchCommissionReport).mockResolvedValue({
      rows: [
        {
          channel: "talabat",
          order_count: 1,
          gross_revenue_aed: "20.00",
          commission_pct: 25,
          commission_aed: "5.00",
          net_revenue_aed: "15.00",
        },
      ],
    });
    vi.mocked(api.fetchProfitReport).mockResolvedValue({
      rows: [
        {
          channel: "talabat",
          order_count: 1,
          gross_revenue_aed: "20.00",
          commission_pct: 25,
          commission_aed: "5.00",
          net_revenue_aed: "15.00",
          food_cost_pct: 30,
          estimated_food_cost_aed: "6.00",
          estimated_profit_aed: "9.00",
        },
      ],
    });
    vi.mocked(api.fetchReconciliation).mockResolvedValue({
      talabat: {
        order_count: 1,
        revenue_aed: "20.00",
        commission_pct: 25,
        commission_aed: "5.00",
        net_aed: "15.00",
      },
    });
  });

  it("renders channels, inbox, and reports", async () => {
    render(<ChannelsScreen />);
    await waitFor(() => {
      expect(screen.getByText("Channels & Aggregators")).toBeInTheDocument();
    });
    expect(await screen.findByTestId("channel-talabat")).toBeInTheDocument();
    expect(screen.getByText("Sync menu")).toBeInTheDocument();
    expect(screen.getByText("TB-1")).toBeInTheDocument();
    expect(screen.getByText("Commission report")).toBeInTheDocument();
    expect(screen.getByText("Profitability by channel")).toBeInTheDocument();
  });
});
