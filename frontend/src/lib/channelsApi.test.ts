import { describe, expect, it, vi } from "vitest";

vi.mock("./apiClient", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import { apiClient } from "./apiClient";
import {
  fetchChannels,
  fetchCommissionReport,
  pauseChannel,
  syncMenu,
} from "./channelsApi";

describe("channelsApi", () => {
  it("fetchChannels hits aggregators channels", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ channels: {}, providers: [] });
    await fetchChannels();
    expect(apiClient.get).toHaveBeenCalledWith("/api/v1/aggregators/channels");
  });

  it("pauseChannel posts pause path", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({});
    await pauseChannel("talabat");
    expect(apiClient.post).toHaveBeenCalledWith(
      "/api/v1/aggregators/channels/talabat/pause",
      {},
    );
  });

  it("syncMenu posts menu sync", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce([]);
    await syncMenu(["talabat"]);
    expect(apiClient.post).toHaveBeenCalledWith("/api/v1/aggregators/sync/menu", {
      providers: ["talabat"],
    });
  });

  it("fetchCommissionReport builds query", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ rows: [] });
    await fetchCommissionReport("2026-07-01", "2026-07-09");
    expect(apiClient.get).toHaveBeenCalledWith(
      "/api/v1/aggregators/reports/commission?start_date=2026-07-01&end_date=2026-07-09",
    );
  });
});
