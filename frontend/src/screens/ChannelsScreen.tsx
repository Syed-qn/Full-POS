import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  createSettlement,
  ensurePublicSlug,
  fetchChannelInbox,
  fetchChannels,
  fetchCommissionReport,
  fetchProfitReport,
  fetchReconciliation,
  pauseChannel,
  providerLiveHealth,
  resumeChannel,
  syncMenu,
  syncPrice,
  syncStock,
  updateChannels,
  type ChannelsOut,
  type CommissionRow,
  type InboxOrder,
  type ProfitRow,
} from "../lib/channelsApi";
import { useManagerPinGate } from "../lib/requireManagerPin";

const AGGREGATOR_KEYS = new Set([
  "talabat",
  "deliveroo",
  "careem",
  "ubereats",
  "noon",
  "zomato",
  "keeta",
]);
import s from "./ChannelsScreen.module.css";

function todayYMD() {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

function daysAgoYMD(n: number) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

export function ChannelsScreen() {
  const [data, setData] = useState<ChannelsOut | null>(null);
  const [inbox, setInbox] = useState<InboxOrder[]>([]);
  const [commission, setCommission] = useState<CommissionRow[]>([]);
  const { requestPin, pinGate, pinBusy } = useManagerPinGate();
  const [profit, setProfit] = useState<ProfitRow[]>([]);
  const [recon, setRecon] = useState<
    Record<string, { order_count: number; revenue_aed: string; commission_aed: string; net_aed: string }>
  >({});
  const [channelFilter, setChannelFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [startDate, setStartDate] = useState(daysAgoYMD(7));
  const [endDate, setEndDate] = useState(todayYMD());
  const [slugInput, setSlugInput] = useState("");
  const [settProvider, setSettProvider] = useState("talabat");
  const [settOrders, setSettOrders] = useState("0");
  const [settGross, setSettGross] = useState("0");
  const [settComm, setSettComm] = useState("0");

  const reload = useCallback(async () => {
    setError(null);
    try {
      const [ch, ib, comm, prof, rc] = await Promise.all([
        fetchChannels(),
        fetchChannelInbox(channelFilter || undefined),
        fetchCommissionReport(startDate, endDate),
        fetchProfitReport(startDate, endDate),
        fetchReconciliation(startDate, endDate),
      ]);
      setData(ch);
      setInbox(ib.orders ?? []);
      setCommission(comm.rows ?? []);
      setProfit(prof.rows ?? []);
      setRecon(rc ?? {});
      if (ch.public_slug) setSlugInput(ch.public_slug);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load channels");
    }
  }, [channelFilter, startDate, endDate]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const channelEntries = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.channels).sort(([a], [b]) => a.localeCompare(b));
  }, [data]);

  const acceptingCount = channelEntries.filter(([, c]) => c.enabled && c.accepting).length;
  const enabledCount = channelEntries.filter(([, c]) => c.enabled).length;
  const inboxOpen = inbox.filter((o) => !["delivered", "cancelled"].includes(o.status)).length;

  function onPause(key: string) {
    requestPin({
      actionType: "channel_pause",
      actionLabel: "Pause sales channel",
      recordLabel: key,
      confirmTitle: `Pause ${key}?`,
      confirmMessage: `Pause accepting orders on ${key}. Manager PIN required.`,
      confirmLabel: "Continue to PIN",
      cancelLabel: "Keep accepting",
      execute: async () => {
        setBusy(true);
        try {
          const next = await pauseChannel(key);
          setData(next);
          toast(`${key} paused`);
        } catch (e) {
          toast(e instanceof Error ? e.message : "Pause failed", "error");
          throw e;
        } finally {
          setBusy(false);
        }
      },
    });
  }

  async function onResume(key: string) {
    setBusy(true);
    try {
      const next = await resumeChannel(key);
      setData(next);
      toast(`${key} accepting orders`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Resume failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onToggleEnabled(key: string, enabled: boolean) {
    setBusy(true);
    try {
      const next = await updateChannels({ [key]: { enabled } });
      setData(next);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Update failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onCommissionChange(key: string, pct: number) {
    setBusy(true);
    try {
      const next = await updateChannels({ [key]: { commission_pct: pct } });
      setData(next);
      toast("Commission saved");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onModeChange(key: string, mode: "mock" | "live") {
    setBusy(true);
    try {
      const next = await updateChannels({ [key]: { mode } });
      setData(next);
      toast(`${key} mode → ${mode}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Mode update failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onSaveLiveCreds(
    key: string,
    fields: {
      api_key?: string;
      api_secret?: string;
      webhook_secret?: string;
      access_token?: string;
      store_id?: string;
      base_url?: string;
    },
  ) {
    setBusy(true);
    try {
      const next = await updateChannels({
        [key]: {
          mode: "live",
          ...fields,
        },
      });
      setData(next);
      toast(`${key}: your restaurant credentials saved (tenant-only)`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Save failed", "error");
    } finally {
      setBusy(false);
    }
  }

  function copyText(label: string, value: string) {
    void navigator.clipboard?.writeText(value).then(
      () => toast(`${label} copied`),
      () => toast("Copy failed", "error"),
    );
  }

  async function onHealth(key: string) {
    setBusy(true);
    try {
      const r = await providerLiveHealth(key);
      toast(
        r.success
          ? `${key} ${r.mode}: OK${r.detail ? ` · ${r.detail}` : ""}`
          : `${key} ${r.mode}: FAIL · ${r.detail ?? ""}`,
        r.success ? "success" : "error",
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "Health check failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onSync(kind: "menu" | "price" | "stock") {
    setBusy(true);
    try {
      const fn = kind === "menu" ? syncMenu : kind === "price" ? syncPrice : syncStock;
      const results = await fn();
      toast(`Synced ${kind} to ${results.length} provider(s)`);
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Sync failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onEnsureSlug() {
    setBusy(true);
    try {
      const next = await ensurePublicSlug(slugInput || undefined);
      setData(next);
      if (next.public_slug) setSlugInput(next.public_slug);
      toast(`Public slug: ${next.public_slug}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Slug failed", "error");
    } finally {
      setBusy(false);
    }
  }

  async function onRecordSettlement() {
    setBusy(true);
    try {
      await createSettlement({
        provider: settProvider,
        period_start: startDate,
        period_end: endDate,
        order_count: Number(settOrders) || 0,
        gross_revenue_aed: settGross || "0",
        commission_aed: settComm || "0",
      });
      toast("Settlement recorded");
      await reload();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Settlement failed", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.screen}>
      <PageHeader
        title="Channels & Aggregators"
        subtitle="Connect each marketplace with this restaurant’s own credentials (multi-tenant SaaS)"
      />

      {error && <p className={s.error}>{error}</p>}

      <div className={s.tenantBanner} data-testid="tenant-credentials-banner" role="note">
        <strong>Your restaurant only.</strong>{" "}
        {data?.tenant_scope ??
          "API keys, secrets, and store IDs are saved on this tenant and never shared with other restaurants."}{" "}
        Switch mode to <em>Live</em>, paste partner credentials, copy the webhook URL into the partner portal, then
        Test connectivity.
        {!data?.public_slug && (
          <>
            {" "}
            Set a <strong>public slug</strong> below so partners get a stable webhook URL.
          </>
        )}
      </div>

      <div className={s.metrics}>
        <div className={s.metric}>
          <span className={s.metricLabel}>Enabled channels</span>
          <strong>{enabledCount}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Accepting now</span>
          <strong>{acceptingCount}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Inbox (open)</span>
          <strong>{inboxOpen}</strong>
        </div>
        <div className={s.metric}>
          <span className={s.metricLabel}>Providers</span>
          <strong>{data?.providers?.length ?? 0}</strong>
        </div>
      </div>

      <div className={s.actions}>
        <Button disabled={busy} onClick={() => void onSync("menu")}>
          Sync menu
        </Button>
        <Button disabled={busy} onClick={() => void onSync("price")}>
          Sync prices
        </Button>
        <Button disabled={busy} onClick={() => void onSync("stock")}>
          Sync stock
        </Button>
        <Button disabled={busy} onClick={() => void reload()}>
          Refresh
        </Button>
      </div>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Public storefront & social order links</h2>
          <span>Website, mobile app, Instagram, Google Business, kiosk share the same slug</span>
        </div>
        <div className={s.row}>
          <label>
            Public slug
            <input value={slugInput} onChange={(e) => setSlugInput(e.target.value)} placeholder="my-restaurant" />
          </label>
          <Button disabled={busy} onClick={() => void onEnsureSlug()}>
            Save slug / generate links
          </Button>
        </div>
        {data?.order_links && (
          <div className={s.grid}>
            {Object.entries(data.order_links)
              .filter(([k]) => k !== "slug")
              .map(([k, url]) => (
                <div key={k} className={s.channelCard}>
                  <div className={s.channelName}>{k.replace("_", " ")}</div>
                  <div className={s.link}>{url || "— set slug first —"}</div>
                </div>
              ))}
          </div>
        )}
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>All channels</h2>
          <span>Enable, pause, and set commission % (Talabat / Deliveroo / Careem / Uber / Noon / Zomato + direct)</span>
        </div>
        <div className={s.grid}>
          {channelEntries.map(([key, cfg]) => (
            <div key={key} className={s.channelCard} data-testid={`channel-${key}`}>
              <div className={s.channelTop}>
                <span className={s.channelName}>{key.replace(/_/g, " ")}</span>
                <div className={s.badges}>
                  <span className={`${s.badge} ${cfg.enabled ? s.badgeOn : s.badgeOff}`}>
                    {cfg.enabled ? "enabled" : "off"}
                  </span>
                  <span className={`${s.badge} ${cfg.accepting ? s.badgeOn : s.badgeOff}`}>
                    {cfg.accepting ? "accepting" : "paused"}
                  </span>
                </div>
              </div>
              <div className={s.row}>
                <Button
                  disabled={busy}
                  onClick={() => void onToggleEnabled(key, !cfg.enabled)}
                >
                  {cfg.enabled ? "Disable" : "Enable"}
                </Button>
                {cfg.accepting ? (
                  <Button disabled={busy || pinBusy || !cfg.enabled} onClick={() => onPause(key)}>
                    Pause
                  </Button>
                ) : (
                  <Button disabled={busy} onClick={() => void onResume(key)}>
                    Resume
                  </Button>
                )}
              </div>
              <div className={s.row}>
                <label>
                  Commission %
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={0.5}
                    defaultValue={cfg.commission_pct}
                    onBlur={(e) => {
                      const v = Number(e.target.value);
                      if (!Number.isNaN(v) && v !== cfg.commission_pct) {
                        void onCommissionChange(key, v);
                      }
                    }}
                  />
                </label>
                <span className={s.badge}>
                  {cfg.mode}
                  {cfg.api_key_set ? " · key✓" : ""}
                </span>
              </div>
              {AGGREGATOR_KEYS.has(key) && (
                <div
                  className={s.integrationPanel}
                  data-testid={`integration-${key}`}
                  style={{ flexDirection: "column", alignItems: "stretch", gap: 8 }}
                >
                  <div className={s.integrationTitle}>Connect {key} (this restaurant)</div>
                  {cfg.credential_hint && (
                    <p className={s.hint} data-testid={`credential-hint-${key}`}>
                      {cfg.credential_hint}
                    </p>
                  )}
                  <label>
                    Adapter mode
                    <select
                      value={cfg.mode === "live" ? "live" : "mock"}
                      onChange={(e) =>
                        void onModeChange(key, e.target.value as "mock" | "live")
                      }
                      disabled={busy}
                      aria-label={`${key} adapter mode`}
                    >
                      <option value="mock">Mock (dev/test)</option>
                      <option value="live">Live — use my partner credentials</option>
                    </select>
                  </label>
                  <label>
                    API key / Client ID / Username (write-only)
                    <input
                      type="password"
                      autoComplete="off"
                      placeholder={cfg.api_key_set ? "•••• saved for this restaurant" : "paste partner key"}
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v) {
                          void onSaveLiveCreds(key, { api_key: v });
                          e.target.value = "";
                        }
                      }}
                    />
                  </label>
                  <label>
                    API secret / Password / Client secret (write-only)
                    <input
                      type="password"
                      autoComplete="new-password"
                      placeholder={
                        cfg.api_secret_set ? "•••• secret saved" : "paste partner secret"
                      }
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v) {
                          void onSaveLiveCreds(key, { api_secret: v });
                          e.target.value = "";
                        }
                      }}
                    />
                  </label>
                  <label>
                    Webhook secret / HMAC key (write-only)
                    <input
                      type="password"
                      autoComplete="new-password"
                      placeholder={
                        cfg.webhook_secret_set
                          ? "•••• webhook secret saved"
                          : "optional partner webhook secret"
                      }
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v) {
                          void onSaveLiveCreds(key, { webhook_secret: v });
                          e.target.value = "";
                        }
                      }}
                    />
                  </label>
                  {(key === "keeta" || key === "ubereats") && (
                    <label>
                      Access token (write-only{key === "keeta" ? " — Keeta merchant token" : ""})
                      <input
                        type="password"
                        autoComplete="off"
                        placeholder={
                          cfg.access_token_set ? "•••• token saved" : "optional pre-issued bearer"
                        }
                        onBlur={(e) => {
                          const v = e.target.value.trim();
                          if (v) {
                            void onSaveLiveCreds(key, { access_token: v });
                            e.target.value = "";
                          }
                        }}
                      />
                    </label>
                  )}
                  <label>
                    Store / Site / Vendor ID
                    <input
                      defaultValue={cfg.store_id ?? ""}
                      placeholder="partner store id for this restaurant"
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v && v !== (cfg.store_id ?? "")) {
                          void onSaveLiveCreds(key, { store_id: v });
                        }
                      }}
                    />
                  </label>
                  <label>
                    Partner / middleware Base URL (optional)
                    <input
                      defaultValue={cfg.base_url ?? ""}
                      placeholder={
                        key === "careem" || key === "noon"
                          ? "https://your-middleware-host/…"
                          : "https://api.partners… (override)"
                      }
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v && v !== (cfg.base_url ?? "")) {
                          void onSaveLiveCreds(key, { base_url: v });
                        }
                      }}
                    />
                  </label>
                  {cfg.webhook_url && (
                    <div className={s.webhookBox} data-testid={`webhook-url-${key}`}>
                      <span className={s.webhookLabel}>Tenant webhook URL (paste in partner portal)</span>
                      <code className={s.webhookUrl}>{cfg.webhook_url}</code>
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => copyText("Webhook URL", cfg.webhook_url!)}
                      >
                        Copy webhook
                      </Button>
                    </div>
                  )}
                  {cfg.partner_webhook_url && (
                    <p className={s.hint}>
                      Alt (X-API-Key): <code>{cfg.partner_webhook_url}</code>
                    </p>
                  )}
                  <div className={s.row}>
                    <span className={s.badge}>
                      {cfg.mode}
                      {cfg.api_key_set ? " · key✓" : ""}
                      {cfg.api_secret_set ? " · secret✓" : ""}
                      {cfg.webhook_secret_set ? " · wh✓" : ""}
                      {cfg.access_token_set ? " · token✓" : ""}
                    </span>
                    <Button disabled={busy} onClick={() => void onHealth(key)}>
                      Test connectivity
                    </Button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Centralized order inbox</h2>
          <span>Filter by channel badge (aggregator + direct)</span>
        </div>
        <div className={s.row}>
          <label>
            Channel filter
            <select value={channelFilter} onChange={(e) => setChannelFilter(e.target.value)}>
              <option value="">All</option>
              {channelEntries.map(([k]) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
          <label>
            From
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            To
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
        </div>
        <table className={s.table}>
          <thead>
            <tr>
              <th>Order</th>
              <th>Channel</th>
              <th>Status</th>
              <th>Total</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {inbox.map((o) => (
              <tr key={o.id}>
                <td>{o.order_number}</td>
                <td>
                  <span className={s.badge}>{o.source_channel}</span>
                </td>
                <td>{o.status}</td>
                <td>{o.total_aed}</td>
                <td>{o.created_at ? o.created_at.slice(0, 16) : "—"}</td>
              </tr>
            ))}
            {inbox.length === 0 && (
              <tr>
                <td colSpan={5}>No orders for this filter</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Commission report</h2>
          <span>Channel-wise fees for the selected range</span>
        </div>
        <table className={s.table}>
          <thead>
            <tr>
              <th>Channel</th>
              <th>Orders</th>
              <th>Gross</th>
              <th>Comm %</th>
              <th>Commission</th>
              <th>Net</th>
            </tr>
          </thead>
          <tbody>
            {commission.map((r) => (
              <tr key={r.channel}>
                <td>{r.channel}</td>
                <td>{r.order_count}</td>
                <td>{r.gross_revenue_aed}</td>
                <td>{r.commission_pct}</td>
                <td>{r.commission_aed}</td>
                <td>{r.net_revenue_aed}</td>
              </tr>
            ))}
            {commission.length === 0 && (
              <tr>
                <td colSpan={6}>No commission data</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Profitability by channel</h2>
          <span>Net after commission − estimated food cost (30%)</span>
        </div>
        <table className={s.table}>
          <thead>
            <tr>
              <th>Channel</th>
              <th>Gross</th>
              <th>Commission</th>
              <th>Food cost</th>
              <th>Est. profit</th>
            </tr>
          </thead>
          <tbody>
            {profit.map((r) => (
              <tr key={r.channel}>
                <td>{r.channel}</td>
                <td>{r.gross_revenue_aed}</td>
                <td>{r.commission_aed}</td>
                <td>{r.estimated_food_cost_aed}</td>
                <td>{r.estimated_profit_aed}</td>
              </tr>
            ))}
            {profit.length === 0 && (
              <tr>
                <td colSpan={5}>No profit data</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Aggregator reconciliation</h2>
          <span>Internal marketplace totals + settlement import</span>
        </div>
        <table className={s.table}>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Orders</th>
              <th>Revenue</th>
              <th>Commission</th>
              <th>Net</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(recon).map(([p, v]) => (
              <tr key={p}>
                <td>{p}</td>
                <td>{v.order_count}</td>
                <td>{v.revenue_aed}</td>
                <td>{v.commission_aed}</td>
                <td>{v.net_aed}</td>
              </tr>
            ))}
            {Object.keys(recon).length === 0 && (
              <tr>
                <td colSpan={5}>No aggregator orders in range</td>
              </tr>
            )}
          </tbody>
        </table>
        <div className={s.row}>
          <label>
            Provider
            <select value={settProvider} onChange={(e) => setSettProvider(e.target.value)}>
              {(data?.providers ?? ["talabat"]).map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label>
            Orders
            <input value={settOrders} onChange={(e) => setSettOrders(e.target.value)} />
          </label>
          <label>
            Gross AED
            <input value={settGross} onChange={(e) => setSettGross(e.target.value)} />
          </label>
          <label>
            Commission AED
            <input value={settComm} onChange={(e) => setSettComm(e.target.value)} />
          </label>
          <Button disabled={busy} onClick={() => void onRecordSettlement()}>
            Record settlement
          </Button>
        </div>
      </section>

      {pinGate}
    </div>
  );
}
