import { useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  ensurePublicSlug,
  fetchChannels,
  pauseChannel,
  providerLiveHealth,
  resumeChannel,
  syncMenu,
  syncPrice,
  syncStock,
  updateChannels,
  type ChannelsOut,
} from "../lib/channelsApi";
import { useManagerPinGate } from "../lib/requireManagerPin";

/** Operator-facing names. The API keys are snake_case identifiers; showing them
 *  raw gave the UI titles like "google business" and "call center". */
const CHANNEL_LABELS: Record<string, string> = {
  talabat: "Talabat",
  deliveroo: "Deliveroo",
  careem: "Careem",
  ubereats: "Uber Eats",
  noon: "Noon Food",
  keeta: "Keeta",
  whatsapp: "WhatsApp",
  website: "Website",
  mobile_app: "Mobile app",
  instagram: "Instagram",
  google_business: "Google Business",
  qr: "QR menu",
  kiosk: "Kiosk",
  call_center: "Call centre",
};

function labelFor(key: string): string {
  return CHANNEL_LABELS[key] ?? key.replace(/_/g, " ");
}

const AGGREGATOR_KEYS = new Set([
  "talabat",
  "deliveroo",
  "careem",
  "ubereats",
  "noon",
  "keeta",
]);
import s from "./ChannelsScreen.module.css";

export function ChannelsScreen() {
  const [data, setData] = useState<ChannelsOut | null>(null);
  const { requestPin, pinGate, pinBusy } = useManagerPinGate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [slugInput, setSlugInput] = useState("");

  const reload = useCallback(async () => {
    setError(null);
    try {
      // Commission and profitability moved to Reports — this screen is channel
      // setup, so it no longer pays for those two round trips on every load.
      const ch = await fetchChannels();
      setData(ch);
      if (ch.public_slug) setSlugInput(ch.public_slug);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load channels");
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const channelEntries = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.channels).sort(([a], [b]) => a.localeCompare(b));
  }, [data]);

  const marketEntries = useMemo(
    () => channelEntries.filter(([k]) => AGGREGATOR_KEYS.has(k)),
    [channelEntries],
  );

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


  return (
    <div className={s.screen}>
      <PageHeader
        title="Channels & Aggregators"
        subtitle="Connect each marketplace with this restaurant’s own credentials (multi-tenant SaaS)"
      />

      {error && <p className={s.error}>{error}</p>}

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
          <h2>Public slug</h2>
          <span>Partner webhook URLs are built from this, so it must be set before a marketplace can call you.</span>
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
      </section>

      <section className={s.card}>
        <div className={s.cardHead}>
          <h2>Marketplaces</h2>
          <span>Talabat, Careem, Noon, Deliveroo and Keeta — credentials, commission and the webhook URL for each partner portal.</span>
        </div>
        <div className={s.marketGrid}>
          {marketEntries.map(([key, cfg]) => (
            <div key={key} className={s.channelCard} data-testid={`channel-${key}`}>
              <div className={s.channelTop}>
                <span className={s.channelName}>{labelFor(key)}</span>
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
                >
                  <div className={s.integrationTitle}>Connect {labelFor(key)}</div>
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

      {pinGate}
    </div>
  );
}
