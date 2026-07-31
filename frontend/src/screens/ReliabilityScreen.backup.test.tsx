import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReliabilityScreen } from "./ReliabilityScreen";

const listBackups = vi.fn();
const getBackupTarget = vi.fn();
const restoreBackup = vi.fn();
const downloadBackup = vi.fn();
const exportDataPack = vi.fn();

vi.mock("../lib/reliabilityApi", () => ({
  getNetworkStatus: () =>
    Promise.resolve({
      devices_online: 1,
      devices_offline: 0,
      devices_total: 1,
      last_backup_at: null,
      unacked_errors: 0,
      devices: [],
    }),
  listBackups: (...a: unknown[]) => listBackups(...a),
  getBackupTarget: (...a: unknown[]) => getBackupTarget(...a),
  restoreBackup: (...a: unknown[]) => restoreBackup(...a),
  downloadBackup: (...a: unknown[]) => downloadBackup(...a),
  exportDataPack: (...a: unknown[]) => exportDataPack(...a),
  listErrors: () => Promise.resolve([]),
  listAuditLog: () => Promise.resolve({ rows: [] }),
  getBackupReadiness: () => Promise.resolve({ orders_count: 18, dishes_count: 51 }),
  createBackup: vi.fn(),
  runDailyBackup: vi.fn(),
  verifyBackup: vi.fn(),
  restorePreview: vi.fn(),
  registerDevice: vi.fn(),
  promoteFailover: vi.fn(),
  ackError: vi.fn(),
}));
vi.mock("../components/Toaster", () => ({ toast: vi.fn() }));

const EPHEMERAL = {
  backend: "local" as const,
  location: "/app/var/backups",
  endpoint: null,
  durable: false,
  note: "Container-local disk. Files are LOST on redeploy or restart. Set APP_BACKUP_DIR to a mounted volume.",
  restore_enabled: true,
  restore_confirm_phrase: "RESTORE 1",
};

const PRESENT = {
  id: 2,
  kind: "manual",
  status: "completed",
  size_bytes: 9663,
  completed_at: "2026-07-31T10:13:32Z",
  file_present: true,
  meta: { backend: "local", counts: { orders: 18, dishes: 51, tables: 7, staff_members: 3 } },
};

describe("ReliabilityScreen — backups tell the truth", () => {
  beforeEach(() => {
    listBackups.mockReset();
    getBackupTarget.mockReset();
    restoreBackup.mockReset();
    downloadBackup.mockReset();
    listBackups.mockResolvedValue([PRESENT]);
    getBackupTarget.mockResolvedValue(EPHEMERAL);
    downloadBackup.mockResolvedValue("r1_manual.json");
    restoreBackup.mockResolvedValue({
      restore_mode: "overwrite",
      pre_restore_backup_id: 9,
      deleted: { orders: 18 },
      inserted: { orders: 18, dishes: 51 },
    });
  });

  it("warns when the backup destination does not survive a redeploy", async () => {
    // The old header said "Snapshots under APP_BACKUP_DIR" — a literal env var
    // name, with nothing about the files being wiped on every deploy.
    render(<ReliabilityScreen />);
    expect(await screen.findByText(/Not durable/)).toBeInTheDocument();
    expect(screen.getByText(/LOST on redeploy/)).toBeInTheDocument();
    expect(screen.getByText(/\/app\/var\/backups/)).toBeInTheDocument();
  });

  it("marks a backup whose file is gone and disables every action on it", async () => {
    listBackups.mockResolvedValue([{ ...PRESENT, id: 3, file_present: false }]);
    render(<ReliabilityScreen />);

    expect(await screen.findByText(/FILE MISSING/)).toBeInTheDocument();
    // Offering Verify/Restore on a row with no file invites a confusing failure.
    for (const label of ["Verify", "Download", "DR preview", "Restore"]) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }
  });

  it("shows what is inside a snapshot, not just its byte count", async () => {
    render(<ReliabilityScreen />);
    // Largest tables first, plus a count of the rest — enough to see the backup
    // caught the day's trading. Scoped to the row: the "Readiness" line above
    // mentions the same numbers, so an unscoped query matches two elements.
    const row = (await screen.findByText("9.4 KB")).closest("tr") as HTMLElement;
    expect(within(row).getByText("51 dishes · 18 orders · 7 tables +1 more")).toBeInTheDocument();
  });

  it("requires the exact typed phrase before restoring", async () => {
    render(<ReliabilityScreen />);
    await userEvent.click(await screen.findByRole("button", { name: "Restore" }));

    const box = await screen.findByTestId("restore-confirm");
    const go = screen.getByRole("button", { name: "Overwrite everything" });
    expect(go).toBeDisabled();

    const input = box.querySelector("input") as HTMLInputElement;
    await userEvent.type(input, "restore 1"); // wrong case
    expect(go).toBeDisabled();

    await userEvent.clear(input);
    await userEvent.type(input, "RESTORE 1");
    expect(go).toBeEnabled();

    await userEvent.click(go);
    await waitFor(() => expect(restoreBackup).toHaveBeenCalledWith(2, "RESTORE 1"));
  });

  it("downloads a real file instead of only toasting a job id", async () => {
    render(<ReliabilityScreen />);
    await userEvent.click(await screen.findByRole("button", { name: "Download" }));
    await waitFor(() => expect(downloadBackup).toHaveBeenCalledWith(2));
  });
});
