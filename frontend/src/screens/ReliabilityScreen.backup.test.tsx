import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReliabilityScreen } from "./ReliabilityScreen";

const listBackups = vi.fn();
const getBackupTarget = vi.fn();
const restoreBackup = vi.fn();
const downloadBackup = vi.fn();
const exportDataPack = vi.fn();
const restorePreview = vi.fn();
const getBackupHealth = vi.fn();
const verifyBackup = vi.fn();

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
  getBackupHealth: (...a: unknown[]) => getBackupHealth(...a),
  createBackup: vi.fn(),
  runDailyBackup: vi.fn(),
  verifyBackup: (...a: unknown[]) => verifyBackup(...a),
  restorePreview: (...a: unknown[]) => restorePreview(...a),
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
    getBackupHealth.mockReset();
    verifyBackup.mockReset();
    getBackupHealth.mockResolvedValue({
      has_backup: true,
      ok: true,
      backup_job_id: 2,
      taken_at: "2026-07-31T12:52:41Z",
      summary: "This backup is complete and can be restored.",
    });
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
    for (const label of ["Check", "Download", "Inspect", "Restore"]) {
      expect(screen.getByRole("button", { name: label })).toBeDisabled();
    }
  });

  it("shows what is inside a snapshot, not just its byte count", async () => {
    render(<ReliabilityScreen />);
    // Largest tables first, plus a count of the rest — enough to see the backup
    // caught the day's trading. Scoped to the row: the "Readiness" line above
    // mentions the same numbers, so an unscoped query matches two elements.
    const row = (await screen.findByText("9.4 KB")).closest("tr") as HTMLElement;
    expect(within(row).getByText("51 dishes, 18 orders, 7 tables and 1 more")).toBeInTheDocument();
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

  it("opens Inspect as a dialog that Escape closes", async () => {
    // It used to render below the table, which with a dozen backups put it off
    // the bottom of the screen — pressing Inspect looked like nothing happened.
    restorePreview.mockResolvedValue({
      restore_mode: "preview_only",
      generated_at: "2026-07-31T12:52:41Z",
      counts: { audit_log: 142, dishes: 51, orders: 0 },
      message: "Snapshot readable.",
    });
    render(<ReliabilityScreen />);
    await userEvent.click(await screen.findByRole("button", { name: "Inspect" }));

    const panel = await screen.findByTestId("backup-preview");
    expect(panel).toHaveAttribute("aria-modal", "true");
    expect(within(panel).getByText("142")).toBeInTheDocument();
    // Empty tables are noise next to the handful that carry the business.
    expect(within(panel).queryByText("orders")).not.toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByTestId("backup-preview")).not.toBeInTheDocument(),
    );
  });

  it("downloads a real file instead of only toasting a job id", async () => {
    render(<ReliabilityScreen />);
    await userEvent.click(await screen.findByRole("button", { name: "Download" }));
    await waitFor(() => expect(downloadBackup).toHaveBeenCalledWith(2));
  });
});

describe("ReliabilityScreen — is my backup actually good?", () => {
  beforeEach(() => {
    listBackups.mockReset();
    getBackupTarget.mockReset();
    getBackupHealth.mockReset();
    verifyBackup.mockReset();
    listBackups.mockResolvedValue([PRESENT]);
    getBackupTarget.mockResolvedValue({ ...EPHEMERAL, durable: true });
  });

  it("states up front whether the newest backup can be restored", async () => {
    // Nobody should have to press a button to learn their data is safe, and a
    // toast that vanishes is not an answer to that question.
    getBackupHealth.mockResolvedValue({
      has_backup: true,
      ok: true,
      backup_job_id: 11,
      taken_at: "2026-07-31T12:52:41Z",
      summary: "This backup is complete and can be restored.",
      backed_up_today: true,
    });
    render(<ReliabilityScreen />);
    // Healthy state is ONE quiet line, not a green panel. Two full-width green
    // banners shouted good news louder than the page shouts bad news.
    const line = await screen.findByTestId("backup-health");
    expect(line).toHaveTextContent("durable");
    expect(line).toHaveTextContent("restorable");
    expect(line).toHaveTextContent("backed up today");
    expect(screen.queryByTestId("backup-health-problem")).not.toBeInTheDocument();
  });

  it("says plainly when the newest backup would NOT restore", async () => {
    getBackupHealth.mockResolvedValue({
      has_backup: true,
      ok: false,
      backup_job_id: 11,
      taken_at: null,
      backed_up_today: true,
      summary:
        "This backup CANNOT be restored: the file has changed since it was written (corrupted).",
    });
    render(<ReliabilityScreen />);
    // Problems still get a panel — that is what the colour is for.
    expect(await screen.findByTestId("backup-health-problem")).toHaveTextContent(
      "CANNOT be restored",
    );
  });

  it("warns when nothing has been backed up today", async () => {
    getBackupHealth.mockResolvedValue({
      has_backup: true,
      ok: true,
      backed_up_today: false,
      summary: "This backup is complete and can be restored.",
    });
    render(<ReliabilityScreen />);
    expect(await screen.findByText(/No backup taken today yet/)).toBeInTheDocument();
  });

  it("leaves the Check verdict on the row instead of a toast", async () => {
    getBackupHealth.mockResolvedValue({
      has_backup: true,
      ok: true,
      backed_up_today: true,
      summary: "ok",
    });
    verifyBackup.mockResolvedValue({
      ok: false,
      restorable: false,
      checks: { checksum_matches: false },
      summary: "This backup CANNOT be restored: the file has changed.",
      checksum: "abc",
    });
    render(<ReliabilityScreen />);
    await userEvent.click(await screen.findByRole("button", { name: "Check" }));

    const verdict = await screen.findByTestId("row-check-2");
    expect(verdict).toHaveTextContent("not restorable");
  });
});

describe("ReliabilityScreen — tabs", () => {
  beforeEach(() => {
    listBackups.mockReset();
    getBackupTarget.mockReset();
    getBackupHealth.mockReset();
    listBackups.mockResolvedValue([PRESENT]);
    getBackupTarget.mockResolvedValue({ ...EPHEMERAL, durable: true });
    getBackupHealth.mockResolvedValue({
      has_backup: true,
      ok: true,
      backed_up_today: true,
      summary: "ok",
    });
  });

  it("hides Devices, which reports numbers that look meaningful and are not", async () => {
    // Promote relabels a row; nothing outside this screen reads the failover
    // flag, and no till registers itself — so the counters describe whoever
    // pressed the button here, not what is running.
    render(<ReliabilityScreen />);
    expect(await screen.findByRole("tab", { name: "Backups" })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Devices" })).not.toBeInTheDocument();
    for (const label of ["Errors & audit", "Conflicts"]) {
      expect(screen.getByRole("tab", { name: label })).toBeInTheDocument();
    }
  });
});
