import { useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import {
  connectMetaEmbedded,
  fetchMetaConfig,
  fetchMetaEmbedConfig,
  saveMetaConfig,
  type MetaConfig,
  type MetaEmbedConfig,
} from "../lib/onboardingApi";
import { loadFacebookSdk } from "../lib/facebookSdk";

/**
 * Onboarding: connect this restaurant's own WhatsApp / Meta account.
 *
 * Preferred path — "Connect with Facebook": launches Meta's Embedded Signup popup
 * (our tech-provider app). The manager logs into their own Meta business, and the
 * popup returns an OAuth code + their phone_number_id + waba_id; the backend
 * exchanges the code for their token and stores it. No manual copy-paste.
 *
 * Fallback path — manual entry: shown when Embedded Signup isn't configured, or when
 * the manager clicks "enter manually". The access token is write-only (never echoed).
 */
export function MetaConnectPanel({ onSaved }: { onSaved?: () => void } = {}) {
  const [cfg, setCfg] = useState<MetaConfig | null>(null);
  const [embed, setEmbed] = useState<MetaEmbedConfig | null>(null);
  const [manual, setManual] = useState(false);
  const [phone, setPhone] = useState("");
  const [waba, setWaba] = useState("");
  const [token, setToken] = useState("");
  const [catalog, setCatalog] = useState("");
  const [busy, setBusy] = useState(false);
  // Embedded Signup posts the business's phone_number_id + waba_id via window
  // messages during the popup; we stash the latest here to pair with the code.
  const sessionInfo = useRef<{ phone_number_id?: string; waba_id?: string }>({});

  useEffect(() => {
    fetchMetaConfig()
      .then((c) => {
        setCfg(c);
        setPhone(c.wa_phone_number_id);
        setWaba(c.wa_business_account_id);
        setCatalog(c.catalog_id);
      })
      .catch(() => {});
    fetchMetaEmbedConfig()
      .then(setEmbed)
      .catch(() => setEmbed({ enabled: false, app_id: "", config_id: "", graph_version: "v21.0" }));
  }, []);

  // Capture the Embedded Signup session info (phone number id + WABA) as it streams.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      let host = "";
      try {
        host = new URL(event.origin).hostname;
      } catch {
        return; // opaque/empty origin — not from the FB popup
      }
      if (!/(^|\.)facebook\.com$/.test(host)) return;
      try {
        const data = JSON.parse(event.data);
        if (data?.type !== "WA_EMBEDDED_SIGNUP") return;
        if (data.event === "FINISH" && data.data) {
          sessionInfo.current = {
            phone_number_id: data.data.phone_number_id,
            waba_id: data.data.waba_id,
          };
        }
      } catch {
        /* non-JSON postMessage — ignore */
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  async function connectWithFacebook() {
    if (!embed?.enabled) return;
    setBusy(true);
    try {
      const FB = await loadFacebookSdk(embed.app_id, embed.graph_version);
      sessionInfo.current = {};
      FB.login(
        async (resp) => {
          const code = resp?.authResponse?.code;
          const info = sessionInfo.current;
          if (!code || !info.phone_number_id || !info.waba_id) {
            toast("Connection cancelled or incomplete — please try again.");
            setBusy(false);
            return;
          }
          try {
            const c = await connectMetaEmbedded({
              code,
              phone_number_id: info.phone_number_id,
              waba_id: info.waba_id,
            });
            setCfg(c);
            setPhone(c.wa_phone_number_id);
            setWaba(c.wa_business_account_id);
            toast("WhatsApp connected ✓");
            if (c.connected) onSaved?.();
          } catch (e) {
            toast(e instanceof Error ? e.message : "Couldn't finish connecting");
          } finally {
            setBusy(false);
          }
        },
        {
          config_id: embed.config_id,
          response_type: "code",
          override_default_response_type: true,
          extras: { setup: {}, sessionInfoVersion: "3" },
        },
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't open the Facebook popup");
      setBusy(false);
    }
  }

  async function saveManual() {
    setBusy(true);
    try {
      const patch: Record<string, string> = {
        wa_phone_number_id: phone.trim(),
        wa_business_account_id: waba.trim(),
        catalog_id: catalog.trim(),
      };
      if (token.trim()) patch.wa_access_token = token.trim();
      const c = await saveMetaConfig(patch);
      setCfg(c);
      setToken("");
      toast(c.connected ? "WhatsApp connected ✓" : "Saved");
      if (c.connected) onSaved?.();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  }

  const field: React.CSSProperties = {
    display: "flex",
    flexDirection: "column",
    gap: 4,
    marginBottom: 10,
  };
  const input: React.CSSProperties = {
    padding: "8px 10px",
    borderRadius: 6,
    border: "1px solid var(--border, #334155)",
    background: "var(--surface, #0f172a)",
    color: "inherit",
  };

  const showManual = manual || (embed !== null && !embed.enabled);

  return (
    <div
      style={{
        border: "1px solid var(--border, #334155)",
        borderRadius: 10,
        padding: 16,
        marginBottom: 18,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ margin: 0 }}>Connect WhatsApp (Meta)</h3>
        <span
          style={{
            fontSize: 12,
            padding: "3px 8px",
            borderRadius: 999,
            background: cfg?.connected ? "#166534" : "#334155",
            color: cfg?.connected ? "#dcfce7" : "#cbd5e1",
          }}
        >
          {cfg?.connected ? "Connected" : "Not connected"}
        </span>
      </div>

      {embed?.enabled && (
        <>
          <p style={{ fontSize: 13, color: "var(--muted, #94a3b8)", marginTop: 6 }}>
            Click below, log in to your Facebook Business, and pick your WhatsApp
            number — we set everything up for you. No tokens to copy.
          </p>
          <button
            type="button"
            onClick={connectWithFacebook}
            disabled={busy}
            style={{
              width: "100%",
              padding: "11px 14px",
              borderRadius: 8,
              border: "none",
              background: "#1877F2",
              color: "#fff",
              fontWeight: 600,
              fontSize: 15,
              cursor: busy ? "default" : "pointer",
              opacity: busy ? 0.7 : 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
            }}
          >
            <span style={{ fontSize: 18, fontWeight: 800 }}>f</span>
            {busy ? "Connecting…" : cfg?.connected ? "Reconnect with Facebook" : "Connect with Facebook"}
          </button>
          <button
            type="button"
            onClick={() => setManual((m) => !m)}
            style={{
              background: "none",
              border: "none",
              color: "var(--muted, #94a3b8)",
              fontSize: 12,
              marginTop: 10,
              cursor: "pointer",
              textDecoration: "underline",
            }}
          >
            {showManual ? "Hide manual entry" : "Enter details manually instead"}
          </button>
        </>
      )}

      {showManual && (
        <div style={{ marginTop: embed?.enabled ? 12 : 6 }}>
          <p style={{ fontSize: 13, color: "var(--muted, #94a3b8)", marginTop: 6 }}>
            Paste from Meta Business Manager → WhatsApp → API Setup. The access token is
            stored securely and never shown again.
          </p>
          <label style={field}>
            <span className="label-upper">WhatsApp Phone Number ID</span>
            <input style={input} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="1234567890" />
          </label>
          <label style={field}>
            <span className="label-upper">WhatsApp Business Account ID (WABA)</span>
            <input style={input} value={waba} onChange={(e) => setWaba(e.target.value)} placeholder="waba-id" />
          </label>
          <label style={field}>
            <span className="label-upper">
              Access Token {cfg?.wa_access_token_set ? "(saved — leave blank to keep)" : ""}
            </span>
            <input
              style={input}
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={cfg?.wa_access_token_set ? "•••••••• (unchanged)" : "EAA..."}
            />
          </label>
          <label style={field}>
            <span className="label-upper">Meta Catalog ID (optional)</span>
            <input style={input} value={catalog} onChange={(e) => setCatalog(e.target.value)} placeholder="catalog-id" />
          </label>
          <Button onClick={saveManual} disabled={busy}>
            {busy ? "Saving…" : "Save connection"}
          </Button>
        </div>
      )}
    </div>
  );
}
