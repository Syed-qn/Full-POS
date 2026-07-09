import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  ackError,
  createBackup,
  exportDataPack,
  getBackupReadiness,
  getNetworkStatus,
  listAuditLog,
  listBackups,
  listDevices,
  listErrors,
  promoteFailover,
  registerDevice,
  restorePreview,
  runDailyBackup,
  verifyBackup,
} from "../lib/reliabilityApi";
import s from "./BranchOpsScreen.module.css";

type Bridge = {
  networkStatus?: () => Promise<{ online: boolean; last_error: string | null }>;
  listConflicts?: () => Promise<Array<{ id: string; entity: string; path: string }>>;
  resolveConflict?: (id: string, action: "retry" | "discard") => Promise<unknown>;
  listPendingOps?: () => Promise<Array<{ id: string; status: string; path: string }>>;
};

function posBridge(): Bridge | undefined {
  return (window as unknown as { posBridge?: Bridge }).posBridge;
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
    Array<{ id: number; kind: string; status: string; size_bytes: number; completed_at: string | null }>
  >([]);
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

  const reload = useCallback(async () => {
    try {
      const [net, bak, err, aud, ready] = await Promise.all([
        getNetworkStatus(),
        listBackups(),
        listErrors(false),
        listAuditLog({ limit: 30 }),
        getBackupReadiness(),
      ]);
      setNetwork(net);
      setBackups(bak);
      setErrors(err);
      setAudit(aud.rows ?? []);
      setReadiness(ready);
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
          <Button type="button" variant="ghost" onClick={() => void reload()}>
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
        <div className={s.metric}>
          <span>Unacked errors</span>
          <strong>{network?.unacked_errors ?? "—"}</strong>
        </div>
        <div className={s.metric}>
          <span>Desktop link</span>
          <strong>
            {desktopOnline === null ? "n/a" : desktopOnline ? "online" : "OFFLINE"}
          </strong>
        </div>
      </section>

      <section className={s.grid}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>Cloud / daily backup</h2>
            <span>
              Snapshots under APP_BACKUP_DIR · last:{" "}
              {readiness?.last_backup_at ?? network?.last_backup_at ?? "never"}
            </span>
          </div>
          <div className={s.actions}>
            <Button type="button" disabled={busy} onClick={() => void doBackup()}>
              Run cloud backup
            </Button>
            <Button
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
              type="button"
              variant="ghost"
              onClick={async () => {
                try {
                  const pack = await exportDataPack();
                  toast(`Export pack job #${pack.backup_job_id}`);
                  await reload();
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Export failed", "error");
                }
              }}
            >
              Full data export
            </Button>
          </div>
          {readiness && (
            <p>
              Readiness: {readiness.orders_count} orders · {readiness.dishes_count} dishes
            </p>
          )}
          <table className={s.table}>
            <thead>
              <tr>
                <th>ID</th>
                <th>Kind</th>
                <th>Status</th>
                <th>Size</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {backups.map((b) => (
                <tr key={b.id}>
                  <td>#{b.id}</td>
                  <td>{b.kind}</td>
                  <td>{b.status}</td>
                  <td>{b.size_bytes}</td>
                  <td>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={async () => {
                        const v = await verifyBackup(b.id);
                        toast(v.ok ? "Checksum OK" : "Checksum FAIL");
                      }}
                    >
                      Verify
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={async () => {
                        const p = await restorePreview(b.id);
                        toast(p.message);
                      }}
                    >
                      DR preview
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>Devices & failover</h2>
            <span>Register terminals; promote standby when primary fails</span>
          </div>
          <div className={s.formGridSingle}>
            <label>
              <span>Device name</span>
              <input value={deviceName} onChange={(e) => setDeviceName(e.target.value)} />
            </label>
          </div>
          <Button
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
          <ul>
            {(network?.devices ?? []).map((d) => (
              <li key={d.device_id}>
                {d.name} · {d.role} · {d.status}
                {d.is_failover_active ? " · FAILOVER" : ""}{" "}
                {d.role !== "primary" && (
                  <Button
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
                )}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className={s.grid}>
        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>Error logs</h2>
            <span>In-app viewer (Sentry optional)</span>
          </div>
          <ul>
            {errors.map((e) => (
              <li key={e.id}>
                [{e.level}] {e.message}{" "}
                {!e.acknowledged && (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={async () => {
                      await ackError(e.id);
                      setErrors(await listErrors());
                    }}
                  >
                    Ack
                  </Button>
                )}
              </li>
            ))}
            {errors.length === 0 && <li>No errors</li>}
          </ul>
        </div>

        <div className={s.card}>
          <div className={s.cardHead}>
            <h2>Admin activity (audit)</h2>
            <span>Append-only trail explorer</span>
          </div>
          <ul>
            {audit.map((a) => (
              <li key={a.id}>
                {a.created_at?.slice(0, 19)} · {a.actor} · {a.entity}/{a.action}
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Offline conflict resolution</h2>
          <span>Desktop shell only — retry or discard 409 conflicts after reconnect</span>
        </div>
        {!posBridge()?.listConflicts && (
          <p>Open the Electron desktop shell to manage offline queue conflicts.</p>
        )}
        <ul>
          {conflicts.map((c) => (
            <li key={c.id}>
              {c.entity} {c.path}{" "}
              <Button
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
            </li>
          ))}
          {conflicts.length === 0 && <li>No conflicts</li>}
        </ul>
      </section>
    </div>
  );
}
