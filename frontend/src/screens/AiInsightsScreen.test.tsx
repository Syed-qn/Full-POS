import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AiInsightsScreen } from "./AiInsightsScreen";

vi.mock("../lib/aiApi", () => ({
  listAiFeatures: vi.fn(),
  listInsights: vi.fn(),
  listReviewReplies: vi.fn(),
  listReservations: vi.fn(),
  listCalls: vi.fn(),
  getCombos: vi.fn(),
  generateDailySales: vi.fn(),
  generateSalesDrop: vi.fn(),
  generateStaffSummary: vi.fn(),
  generateSlowMoving: vi.fn(),
  generateFoodCost: vi.fn(),
  generateLowStock: vi.fn(),
  generateSegments: vi.fn(),
  generateBundles: vi.fn(),
  generateFestival: vi.fn(),
  suggestReviewReply: vi.fn(),
  escalateNegativeReviews: vi.fn(),
  translateMenu: vi.fn(),
  createReservation: vi.fn(),
  startCall: vi.fn(),
  turnCall: vi.fn(),
  abandonedCopy: vi.fn(),
  reorderPrompt: vi.fn(),
}));

import * as api from "../lib/aiApi";

describe("AiInsightsScreen", () => {
  beforeEach(() => {
    vi.mocked(api.listAiFeatures).mockResolvedValue({
      features: [
        { key: "daily_sales", status: "implemented", path: "/api/v1/ai/insights/daily-sales" },
        { key: "call_answering", status: "implemented" },
      ],
    });
    vi.mocked(api.listInsights).mockResolvedValue([]);
    vi.mocked(api.listReviewReplies).mockResolvedValue([]);
    vi.mocked(api.listReservations).mockResolvedValue([]);
    vi.mocked(api.listCalls).mockResolvedValue([]);
    vi.mocked(api.getCombos).mockResolvedValue({ combos: [] });
  });

  it("renders AI insights dashboard", async () => {
    render(<AiInsightsScreen />);
    await waitFor(() => {
      expect(screen.getByText("AI Insights")).toBeInTheDocument();
    });
    expect(screen.getByText("Daily sales summary")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/daily_sales/)).toBeInTheDocument();
    });
  });
});
