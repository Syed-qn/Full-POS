import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { MetaConnectPanel } from "../components/MetaConnectPanel";
import { toast } from "../components/Toaster";
import { writeCachedOnboardingComplete } from "../lib/onboardingGate";
import { completeOnboarding, fetchOnboardingStatus } from "../lib/onboardingApi";
import s from "./OnboardingScreen.module.css";

/**
 * Onboarding is a single gate: connect WhatsApp (Meta). Menu, location and the
 * Meta catalogue are configured afterwards inside the dashboard. Once connected
 * we finish and drop the manager straight into ops.
 */
export function OnboardingScreen() {
  const nav = useNavigate();
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshStatus() {
    const st = await fetchOnboardingStatus();
    setConnected(st.has_meta);
    if (st.complete) nav("/menu", { replace: true });
  }

  useEffect(() => {
    refreshStatus().catch(() => {});
  }, []);

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      await completeOnboarding();
      writeCachedOnboardingComplete(true);
      toast("You're all set — welcome to your dashboard");
      nav("/menu", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connect your WhatsApp account first");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={s.screen}>
      <div className={s.wrap}>
        <div className={s.brand}>
          <span className={s.brandIcon}>▸</span> OPS TERMINAL
        </div>

        <h1 className={s.title}>Connect your WhatsApp</h1>
        <p className={s.sub}>
          Link your WhatsApp (Meta) account to get started. Everything else is set up
          inside your dashboard.
        </p>

        {error && (
          <SectionBanner tone="error" onDismiss={() => setError(null)}>
            {error}
          </SectionBanner>
        )}

        <MetaConnectPanel onSaved={refreshStatus} />

        <div className={s.card}>
          {connected ? (
            <div className={s.connectedCard}>
              <span className={s.checkPill}>✓</span>
              <p className={s.hint}>WhatsApp connected — you&apos;re ready to go.</p>
              <Button onClick={finish} disabled={busy}>
                {busy ? "Opening…" : "Go to dashboard"}
              </Button>
            </div>
          ) : (
            <p className={s.warn}>Connect your WhatsApp (Meta) account above to continue.</p>
          )}
        </div>

        <div className={s.nextLabel}>Set up next — inside your dashboard</div>
        <div className={s.next}>
          <span className={s.nextChip}>Menu</span>
          <span className={s.nextChip}>Location</span>
          <span className={s.nextChip}>Catalogue</span>
          <span className={s.nextChip}>Riders</span>
        </div>
      </div>
    </div>
  );
}
