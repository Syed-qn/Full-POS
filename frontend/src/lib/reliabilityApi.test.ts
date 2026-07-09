import { describe, expect, it, vi } from "vitest";

vi.mock("./apiClient", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { apiClient } from "./apiClient";
import { createBackup, getNetworkStatus, listBackups } from "./reliabilityApi";

describe("reliabilityApi", () => {
  it("getNetworkStatus hits reliability endpoint", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ devices_online: 1 });
    await getNetworkStatus();
    expect(apiClient.get).toHaveBeenCalledWith("/api/v1/reliability/network-status");
  });

  it("createBackup posts with kind", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ id: 1 });
    await createBackup("daily");
    expect(apiClient.post).toHaveBeenCalledWith(
      "/api/v1/reliability/backups?kind=daily",
      {},
    );
  });

  it("listBackups gets list", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce([]);
    await listBackups();
    expect(apiClient.get).toHaveBeenCalledWith("/api/v1/reliability/backups");
  });
});
