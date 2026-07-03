import type { CampaignResponse } from "./marketingApi";

/** Campaigns that actually ran (or are actively sending). */
export const SENT_CAMPAIGN_STATUSES = new Set(["sent", "sending"]);

export interface CampaignSummary {
  campaignsSent: number;
  messagesDelivered: number;
  ordersFromCampaigns: number;
  successRate: number;
}

export function statNum(stats: Record<string, unknown>, key: string): number {
  const v = stats[key];
  return typeof v === "number" ? v : 0;
}

export function toYMD(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function filterCampaignsByDate(
  campaigns: CampaignResponse[],
  bounds: { fromDate?: string; toDate?: string },
): CampaignResponse[] {
  const { fromDate, toDate } = bounds;
  if (!fromDate && !toDate) return campaigns;
  return campaigns.filter((c) => {
    const raw = c.created_at;
    if (!raw) return false;
    const day = toYMD(new Date(raw));
    if (fromDate && day < fromDate) return false;
    if (toDate && day > toDate) return false;
    return true;
  });
}

export function computeCampaignSummary(
  campaigns: CampaignResponse[],
): CampaignSummary | null {
  if (campaigns.length === 0) return null;
  const campaignsSent = campaigns.filter((c) =>
    SENT_CAMPAIGN_STATUSES.has(c.status),
  ).length;
  const messagesDelivered = campaigns.reduce(
    (acc, c) => acc + statNum(c.stats, "sent"),
    0,
  );
  const ordersFromCampaigns = campaigns.reduce(
    (acc, c) => acc + statNum(c.stats, "converted"),
    0,
  );
  return {
    campaignsSent,
    messagesDelivered,
    ordersFromCampaigns,
    successRate:
      messagesDelivered > 0
        ? Math.round((ordersFromCampaigns / messagesDelivered) * 100)
        : 0,
  };
}