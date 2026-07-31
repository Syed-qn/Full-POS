import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  type BackupTarget,
  ackError,
  createBackup,
  downloadBackup,
  exportDataPack,
  getBackupReadiness,
  getBackupTarget,
  getNetworkStatus,
  listAuditLog,
  listBackups,
  listErrors,
  promoteFailover,
  registerDevice,
  restoreBackup,
  restorePreview,
  runDailyBackup,
  verifyBackup,
} from "../lib/reliabilityApi";
import s from "./ReliabilityScreen.module.css";

type RelTab = "backups" | "devices" | "errors" | "conflicts";

type Bridge = {
  networkStatus?: () => Promise<{ online: boolean; last_error: string | null }>;
  listConflicts?: () => Promise<Array<{ id: string; entity: string; path: string }>>;
  resolveConflict?: (id: string, action: "retry" | "discard") => Promise<unknown>;
  listPendingOps?: () => Promise<Array<{ id: string; status: string; path: string }>>;
};

function posBridge(): Bridge | undefined {
  return (window as unknown as { posBridge?: Bridge }).posBridge;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** The three biggest tables in the snapshot — enough to see at a glance whether
 *  a backup actually caught the day's trading. */
function summarise(meta: { counts?: Record<string, number> } | null): string {
  const counts = meta?.counts;
  if (!counts) return "—";
  const top = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k, v]) => `${v} ${k}`);
  const rest = Object.keys(counts).length - top.length;
  // "+N more", not "+N tables" — `tables` is itself one of the table names here.
  return rest > 0 ? `${top.join(" · ")} +${rest} more` : top.join(" · ");
}

export function ReliabilityScreen() {
  const [network, setNetwork] = useState<{
    devices_online: number;
    devices_offline: number;
    last_backup_at: string | null;
    unacked_errors: number;
    devices: Array<{
      device_id: string;
      name: string;
      role: string;
      status: string;
      is_failover_active: boolean;
    }>;
  } | null>(null);
  const [backups, setBackups] = useState<
    Array<{
      id: number;
      kind: string;
      status: string;
      size_bytes: number;
      completed_at: string | null;
      file_present: boolean;
      meta: { backend?: string; counts?: Record<string, number> } | null;
    }>
  >([]);
  const [target, setTarget] = useState<BackupTarget | null>(null);
  const [errors, setErrors] = useState<
    Array<{ id: number; message: string; level: string; acknowledged: boolean }>
  >([]);
  const [audit, setAudit] = useState<
    Array<{ id: number; actor: string; entity: string; action: string; created_at: string }>
  >([]);
  const [readiness, setReadiness] = useState<{
    orders_count: number;
    dishes_count: number;
    last_backup_at?: string | null;
  } | null>(null);
  const [desktopOnline, setDesktopOnline] = useState<boolean | null>(null);
  const [conflicts, setConflicts] = useState<Array<{ id: string; entity: string; path: string }>>([]);
  const [deviceName, setDeviceName] = useState("Dashboard browser");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<RelTab>("backups");
  const [preview, setPreview] = useState<{
    id: number;
    generated_at?: string;
    counts?: Record<string, number>;
    message?: string;
  } | null>(null);
  const [restoreFor, setRestoreFor] = useState<number | null>(null);
  const [restoreConfirm, setRestoreConfirm] = useState("");

  const reload = useCallback(async () => {
    try {
      const [net, bak, err, aud, ready, tgt] = await Promise.all([
        getNetworkStatus(),
        listBackups(),
        listErrors(false),
        listAuditLog({ limit: 30 }),
        getBackupReadiness(),
        getBackupTarget(),
      ]);
      setNetwork(net);
      setBackups(bak);
      setErrors(err);
      setAudit(aud.rows ?? []);
      setReadiness(ready);
      setTarget(tgt);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Load failed", "error");
    }
    const bridge = posBridge();
    if (bridge?.networkStatus) {
      try {
        const st = await bridge.networkStatus();
        setDesktopOnline(st.online);
      } catch {
        setDesktopOnline(null);
      }
    }
    if (bridge?.listConflicts) {
      try {
        setConflicts(await bridge.listConflicts());
      } catch {
        setConflicts([]);
      }
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function doBackup() {
    setBusy(true);
    try {
      const job = await createBackup("cloud");
      toast(`Backup #${job.id} completed (${job.size_bytes} bytes)`);
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Backup failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.screen}>
      <PageHeader
        title="Reliability"
        subtitle="Offline sync, cloud backups, device failover, errors & audit"
        right={
          <Button size="md" type="button" variant="ghost" onClick={() => void reload()}>
            Refresh
          </Button>
        }
      />

      <section className={s.metrics}>
        <div className={s.metric}>
          <span>Devices online</span>
          <strong>{network?.devices_online ?? "—"}</strong>
        </div>
        <div className={s.metric}>
          <span>Devices offline</span>
          <strong>{network?.devices_offline ?? "—"}</strong>
        </div>
        <div className={`${s.metric} ${(network?.unacked_errors ?? 0) > 0 ? s.metricAlert : ""}`}>
          <span>Unacked errors</span>
          <strong>{network?.unacked_errors ?? "—"}</strong>
        </div>
        <div className={`${s.metric} ${desktopOnline === false ? s.metricAlert : ""}`}>
          <span>Desktop link</span>
          <strong>
            {desktopOnline === null ? "n/a" : desktopOnline ? "online" : "OFFLINE"}
          </strong>
        </div>
      </section>

      <div className={s.tabs} role="tablist" aria-label="Reliability sections">
        {(
          [
            ["backups", "Backups"],
            ["devices", "Devices"],
            ["errors", "Errors & audit"],
            ["conflicts", "Conflicts"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`${s.tab} ${tab === key ? s.tabActive : ""}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "backups" && (
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>Backups</h2>
            <span>
              {target
                ? `${target.backend === "s3" ? "Object storage" : "Local disk"} · ${target.location}`
                : "Loading destination…"}
              {" · last: "}
              {readiness?.last_backup_at ?? network?.last_backup_at ?? "never"}
            </span>
          </div>
          {/* The single most important fact on this screen: a backup you cannot
              retrieve is not a backup. Stated up front rather than discovered
              later when Verify starts failing. */}
          {target && (
            <p className={target.durable ? s.noteOk : s.noteWarn}>
              {target.durable ? "✓ Durable — " : "⚠ Not durable — "}
              {target.note}
            </p>
          )}
          <div className={s.actions}>
            <Button size="md" type="button" disabled={busy} onClick={() => void doBackup()}>
              Run cloud backup
            </Button>
            <Button
              size="md"
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={async () => {
                try {
                  await runDailyBackup();
                  toast("Daily backup ensured");
                  await reload();
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Failed", "error");
                }
              }}
            >
              Ensure daily backup
            </Button>
            <Button
              size="md"
              type="button"
              variant="ghost"
              onClick={async () => {
                setBusy(true);
                try {
                  // Take the snapshot, then actually put the file on the
                  // manager's machine — the old version only toasted a job id.
                  const pack = await exportDataPack();
                  const name = await downloadBackup(pack.backup_job_id);
                  toast(`Downloaded ${name} (${pack.size_bytes} bytes)`);
                  await reload();
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Export failed", "error");
                } finally {
                  setBusy(false);
                }
              }}
            >
              Export &amp; download
            </Button>
          </div>
          {readiness && (
            <p className={s.muted}>
              Readiness: {readiness.orders_count} orders · {readiness.dishes_count} dishes
            </p>
          )}
          {backups.length === 0 ? (
            <EmptyState title="No backups yet" description="Run a cloud backup to create the first snapshot." />
          ) : (
            <div className={s.tableWrap}>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Kind</th>
                    <th>Status</th>
                    <th>Size</th>
                    <th>Contents</th>
                    <th>Actions</th>
                  </tr>
                </thead>
              <tbody>
                {backups.map((b) => (
                  <tr key={b.id}>
                    <td>#{b.id}</td>
                    <td>{b.kind}</td>
                    <td>
                      {b.status}
                      {/* "completed" alone is misleading once the file is gone. */}
                      {!b.file_present && <span className={s.gone}> · FILE MISSING</span>}
                    </td>
                    <td>{formatBytes(b.size_bytes)}</td>
                    <td className={s.muted}>{summarise(b.meta)}</td>
                    <td>
                      <div className={s.rowActions}>
                        <Button
                          size="md"
                          type="button"
                          variant="ghost"
                          disabled={!b.file_present}
                          onClick={async () => {
                            try {
                              const v = await verifyBackup(b.id);
                              toast(v.ok ? "Checksum OK" : "Checksum FAIL", v.ok ? "success" : "error");
                            } catch (e) {
                              toast(e instanceof Error ? e.message : "Verify failed", "error");
                            }
                          }}
                        >
                          Verify
                        </Button>
                        <Button
                          size="md"
                          type="button"
                          variant="ghost"
                          disabled={!b.file_present}
                          onClick={async () => {
                            try {
                              const name = await downloadBackup(b.id);
                              toast(`Downloaded ${name}`);
                            } catch (e) {
                              toast(e instanceof Error ? e.message : "Download failed", "error");
                            }
                          }}
                        >
                          Download
                        </Button>
                        <Button
                          size="md"
                          type="button"
                          variant="ghost"
                          disabled={!b.file_present}
                          onClick={async () => {
                            try {
                              // A toast could not show what is actually in the
                              // snapshot, which is the only question this button
                              // exists to answer.
                              const p = await restorePreview(b.id);
                              setPreview({ id: b.id, ...p });
                            } catch (e) {
                              toast(e instanceof Error ? e.message : "Preview failed", "error");
                            }
                          }}
                        >
                          Inspect
                        </Button>
                        <Button
                          size="md"
                          type="button"
                          variant="danger"
                          disabled={!b.file_present || busy}
                          onClick={() => setRestoreFor(b.id)}
                        >
                          Restore
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                </tbody>
              </table>
            </div>
          )}

          {preview && (
            <div className={s.previewBox} data-testid="backup-preview">
              <div className={s.previewHead}>
                <h3>Inside backup #{preview.id}</h3>
                <Button size="md" type="button" variant="ghost" onClick={() => setPreview(null)}>
                  Close
                </Button>
              </div>
              <p className={s.muted}>Taken {preview.generated_at ?? "—"}</p>
              {/* Only tables that hold something. Listing ~120 empty ones would
                  bury the handful that matter. */}
              <div className={s.previewGrid}>
                {Object.entries(preview.counts ?? {})
                  .filter(([, v]) => v > 0)
                  .sort((a, b) => b[1] - a[1])
                  .map(([name, n]) => (
                    <div key={name} className={s.previewCell}>
                      <strong>{n}</strong>
                      <span>{name.replace(/_/g, " ")}</span>
                    </div>
                  ))}
              </div>
              {preview.message && <p className={s.muted}>{preview.message}</p>}
            </div>
          )}

          {restoreFor !== null && target && (
            <div className={s.restoreBox} data-testid="restore-confirm">
              <h3>Restore backup #{restoreFor}</h3>
              <p>
                This <strong>deletes this restaurant's current data</strong> and replaces it
                with the snapshot. Orders, tables, staff, payments and settings all revert.
                A <code>pre_restore</code> backup is taken first, so this can be undone.
              </p>
              {!target.restore_enabled && (
                <p className={s.noteWarn}>
                  ⚠ Restore is switched off on this server. Set
                  {" "}<code>APP_BACKUP_RESTORE_ENABLED=true</code> to allow it.
                </p>
              )}
              <label>
                <span>
                  Type <code>{target.restore_confirm_phrase}</code> to confirm
                </span>
                <input
                  value={restoreConfirm}
                  onChange={(e) => setRestoreConfirm(e.target.value)}
                  placeholder={target.restore_confirm_phrase}
                  autoFocus
                />
              </label>
              <div className={s.rowActions}>
                <Button
                  size="md"
                  type="button"
                  variant="danger"
                  disabled={busy || restoreConfirm !== target.restore_confirm_phrase}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      const r = await restoreBackup(restoreFor, restoreConfirm);
                      const rows = Object.values(r.inserted).reduce((a, b) => a + b, 0);
                      toast(
                        `Restored ${rows} rows · undo with backup #${r.pre_restore_backup_id}`,
                      );
                      setRestoreFor(null);
                      setRestoreConfirm("");
                      await reload();
                    } catch (e) {
                      toast(e instanceof Error ? e.message : "Restore failed", "error");
                    } finally {
                      setBusy(false);
                    }
                  }}
                >
                  Overwrite everything
                </Button>
                <Button
                  size="md"
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    setRestoreFor(null);
                    setRestoreConfirm("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "devices" && (
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>Devices & failover</h2>
            <span>Register terminals; promote standby when primary fails</span>
          </div>
          <div className={s.registerRow}>
          <div className={s.formGridSingle}>
            <label>
              <span>Device name</span>
              <input value={deviceName} onChange={(e) => setDeviceName(e.target.value)} />
            </label>
          </div>
          <Button
            size="md"
            type="button"
            onClick={async () => {
              const deviceId =
                localStorage.getItem("pos_device_id") ||
                `web-${Math.random().toString(36).slice(2, 10)}`;
              localStorage.setItem("pos_device_id", deviceId);
              await registerDevice({
                device_id: deviceId,
                name: deviceName,
                device_type: "pos",
                role: "primary",
              });
              toast("Device registered");
              await reload();
            }}
          >
            Register this browser
          </Button>
          </div>
          <ul className={s.list}>
            {(network?.devices ?? []).map((d) => (
              <li key={d.device_id} className={s.listItem}>
                <span>
                  {d.name} · {d.role} · {d.status}
                  {d.is_failover_active ? " · FAILOVER" : ""}
                </span>
                {d.role !== "primary" && (
                  <div className={s.listActions}>
                    <Button
                      size="md"
                      type="button"
                      variant="ghost"
                      onClick={async () => {
                        await promoteFailover(d.device_id);
                        toast("Failover promoted");
                        await reload();
                      }}
                    >
                      Promote
                    </Button>
                  </div>
                )}
              </li>
            ))}
            {(network?.devices ?? []).length === 0 && (
              <li>
                <EmptyState title="No devices" description="Register this browser as a POS terminal." />
              </li>
            )}
          </ul>
        </div>
      )}

      {tab === "errors" && (
        <section className={s.grid}>
          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>Error logs</h2>
              <span>In-app viewer (Sentry optional)</span>
            </div>
            {errors.length === 0 ? (
              <EmptyState title="No errors" description="Unacked application errors will show here." />
            ) : (
              <ul className={s.list}>
                {errors.map((e) => (
                  <li key={e.id} className={s.listItem}>
                    <span>
                      [{e.level}] {e.message}
                    </span>
                    {!e.acknowledged && (
                      <div className={s.listActions}>
                        <Button
                          size="md"
                          type="button"
                          variant="ghost"
                          onClick={async () => {
                            await ackError(e.id);
                            setErrors(await listErrors());
                          }}
                        >
                          Ack
                        </Button>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className={s.card}>
            <div className={s.cardHead}>
              <h2>Admin activity (audit)</h2>
              <span>Append-only trail explorer</span>
            </div>
            {audit.length === 0 ? (
              <EmptyState title="No audit rows" description="Manager actions appear in this trail." />
            ) : (
              <ul className={s.list}>
                {audit.map((a) => (
                  <li key={a.id} className={s.listItem}>
                    <span>
                      {a.created_at?.slice(0, 19)} · {a.actor} · {a.entity}/{a.action}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}

      {tab === "conflicts" && (
        <section className={s.card}>
          <div className={s.cardHead}>
            <h2>Offline conflict resolution</h2>
            <span>Desktop shell only — retry or discard 409 conflicts after reconnect</span>
          </div>
          {!posBridge()?.listConflicts && (
            <p className={s.muted}>Open the Electron desktop shell to manage offline queue conflicts.</p>
          )}
          {conflicts.length === 0 ? (
            <EmptyState title="No conflicts" description="Sync conflicts after reconnect will list here." />
          ) : (
            <ul className={s.list}>
              {conflicts.map((c) => (
                <li key={c.id} className={s.listItem}>
                  <span>
                    {c.entity} {c.path}
                  </span>
                  <div className={s.listActions}>
                    <Button
                      size="md"
                      type="button"
                      variant="ghost"
                      onClick={async () => {
                        await posBridge()?.resolveConflict?.(c.id, "retry");
                        toast("Queued for retry");
                        setConflicts((await posBridge()?.listConflicts?.()) ?? []);
                      }}
                    >
                      Retry
                    </Button>
                    <Button
                      size="md"
                      type="button"
                      variant="ghost"
                      onClick={async () => {
                        await posBridge()?.resolveConflict?.(c.id, "discard");
                        toast("Discarded");
                        setConflicts((await posBridge()?.listConflicts?.()) ?? []);
                      }}
                    >
                      Discard
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
