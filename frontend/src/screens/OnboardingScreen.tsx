import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { SectionBanner } from "../components/SectionBanner";
import { MetaConnectPanel } from "../components/MetaConnectPanel";
import { toast } from "../components/Toaster";
import { writeCachedOnboardingComplete } from "../lib/onboardingGate";
import { completeOnboarding, fetchOnboardingStatus } from "../lib/onboardingApi";
import { logout } from "../lib/auth";
import s from "./OnboardingScreen.module.css";

/**
 * Onboarding is a single gate: connect WhatsApp (Meta). The moment the account is
 * connected we finalize and drop the manager straight into ops, where menu,
 * location and the catalogue are configured.
 */
export function OnboardingScreen() {
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);

  // Connected → finalize onboarding + go to ops.
  async function onConnected() {
    try {
      await completeOnboarding();
      writeCachedOnboardingComplete(true);
      toast("You're all set. Welcome to your dashboard");
    } catch {
      /* complete gates on Meta; if it races, the router gate still lets them in */
    }
    nav("/menu", { replace: true });
  }

  async function refreshStatus() {
    try {
      const st = await fetchOnboardingStatus();
      if (st.has_meta) await onConnected();
    } catch {
      setError("Couldn't load your status. Please retry.");
    }
  }

  useEffect(() => {
    refreshStatus().catch(() => {});
  }, []);

  function signOut() {
    logout();
    nav("/login", { replace: true });
  }

  return (
    <div className={s.screen}>
      <div className={s.wrap}>
        <div className={s.brand}>
          <span className={s.brandIcon}>▸</span> OPS TERMINAL
        </div>

        {error && (
          <SectionBanner tone="error" onDismiss={() => setError(null)}>
            {error}
          </SectionBanner>
        )}

        <MetaConnectPanel onSaved={refreshStatus} hideBadge />

        <p className={s.foot}>
          Menu, location &amp; catalogue are set up inside your dashboard.
        </p>
        <button type="button" className={s.signout} onClick={signOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}
