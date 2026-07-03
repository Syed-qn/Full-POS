import { describe, expect, it } from "vitest";
import type { CampaignResponse } from "./marketingApi";
import {
  computeCampaignSummary,
  filterCampaignsByDate,
  statNum,
} from "./campaignSummary";

function camp(
  partial: Partial<CampaignResponse> & Pick<CampaignResponse, "id" | "status">,
): CampaignResponse {
  return {
    type: "promotional",
    stats: {},
    ...partial,
  };
}

describe("campaignSummary", () => {
  it("statNum returns 0 for missing or non-numeric values", () => {
    expect(statNum({}, "sent")).toBe(0);
    expect(statNum({ sent: "x" }, "sent")).toBe(0);
    expect(statNum({ sent: 12 }, "sent")).toBe(12);
  });

  it("computeCampaignSummary counts only sent/sending campaigns for campaignsSent", () => {
    const campaigns = [
      camp({ id: 1, status: "sent", stats: { sent: 100, converted: 10 } }),
      camp({ id: 2, status: "draft", stats: { sent: 0, converted: 0 } }),
      camp({ id: 3, status: "sending", stats: { sent: 5, converted: 0 } }),
    ];
    const summary = computeCampaignSummary(campaigns);
    expect(summary).toEqual({
      campaignsSent: 2,
      messagesDelivered: 105,
      ordersFromCampaigns: 10,
      successRate: 10,
    });
  });

  it("returns null when no campaigns", () => {
    expect(computeCampaignSummary([])).toBeNull();
  });

  it("filterCampaignsByDate keeps rows within inclusive YMD bounds", () => {
    const campaigns = [
      camp({ id: 1, status: "sent", created_at: "2026-07-01T10:00:00Z" }),
      camp({ id: 2, status: "sent", created_at: "2026-07-03T10:00:00Z" }),
      camp({ id: 3, status: "sent", created_at: "2026-07-05T10:00:00Z" }),
    ];
    const filtered = filterCampaignsByDate(campaigns, {
      fromDate: "2026-07-02",
      toDate: "2026-07-04",
    });
    expect(filtered.map((c) => c.id)).toEqual([2]);
  });
});