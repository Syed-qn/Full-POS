import { useEffect, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import {
  fetchMetaConfig,
  saveMetaConfig,
  type MetaConfig,
} from "../lib/onboardingApi";

/**
 * Onboarding: connect this restaurant's own WhatsApp / Meta account.
 * The manager pastes the values from Meta Business Manager (or, later, an
 * Embedded Signup flow fills them automatically). The access token is write-only
 * — the server never returns it, only whether one is set.
 */
export function MetaConnectPanel() {
  const [cfg, setCfg] = useState<MetaConfig | null>(null);
  const [phone, setPhone] = useState("");
  const [waba, setWaba] = useState("");
  const [token, setToken] = useState("");
  const [catalog, setCatalog] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchMetaConfig()
      .then((c) => {
        setCfg(c);
        setPhone(c.wa_phone_number_id);
        setWaba(c.wa_business_account_id);
        setCatalog(c.catalog_id);
      })
      .catch(() => {});
  }, []);

  async function save() {
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

      <Button onClick={save} disabled={busy}>
        {busy ? "Saving…" : "Save connection"}
      </Button>
    </div>
  );
}
