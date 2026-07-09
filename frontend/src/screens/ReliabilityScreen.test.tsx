import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReliabilityScreen } from "./ReliabilityScreen";

vi.mock("../lib/reliabilityApi", () => ({
  getNetworkStatus: vi.fn(),
  listBackups: vi.fn(),
  listErrors: vi.fn(),
  listAuditLog: vi.fn(),
  getBackupReadiness: vi.fn(),
  createBackup: vi.fn(),
  runDailyBackup: vi.fn(),
  exportDataPack: vi.fn(),
  verifyBackup: vi.fn(),
  restorePreview: vi.fn(),
  listDevices: vi.fn(),
  registerDevice: vi.fn(),
  promoteFailover: vi.fn(),
  ackError: vi.fn(),
}));

import * as api from "../lib/reliabilityApi";

describe("ReliabilityScreen", () => {
  beforeEach(() => {
    vi.mocked(api.getNetworkStatus).mockResolvedValue({
      devices_online: 2,
      devices_offline: 0,
      devices_total: 2,
      last_backup_at: "2026-07-09T10:00:00Z",
      unacked_errors: 0,
      devices: [
        {
          device_id: "d1",
          name: "POS1",
          role: "primary",
          status: "online",
          is_failover_active: false,
        },
      ],
    });
    vi.mocked(api.listBackups).mockResolvedValue([
      {
        id: 1,
        kind: "manual",
        status: "completed",
        size_bytes: 100,
        checksum: "abc",
        completed_at: "2026-07-09T10:00:00Z",
        storage_path: "/tmp/b.json",
      },
    ]);
    vi.mocked(api.listErrors).mockResolvedValue([]);
    vi.mocked(api.listAuditLog).mockResolvedValue({ rows: [] });
    vi.mocked(api.getBackupReadiness).mockResolvedValue({
      orders_count: 0,
      customers_count: 0,
      dishes_count: 4,
      last_backup_at: "2026-07-09T10:00:00Z",
    });
  });

  it("renders reliability dashboard", async () => {
    render(<ReliabilityScreen />);
    await waitFor(() => {
      expect(screen.getByText("Reliability")).toBeInTheDocument();
    });
    expect(screen.getByText("Run cloud backup")).toBeInTheDocument();
    await screen.getByRole("tab", { name: /devices/i }).click();
    await waitFor(() => {
      expect(screen.getByText(/POS1/)).toBeInTheDocument();
    });
  });
});
