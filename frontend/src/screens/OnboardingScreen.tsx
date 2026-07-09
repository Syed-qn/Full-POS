import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BottomActionBar } from "../components/BottomActionBar";
import { Button, TouchButton } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { MetaConnectPanel } from "../components/MetaConnectPanel";
import { toast } from "../components/Toaster";
import { writeCachedOnboardingComplete } from "../lib/onboardingGate";
import { completeOnboarding, fetchOnboardingStatus } from "../lib/onboardingApi";
import { logout } from "../lib/auth";
import s from "./OnboardingScreen.module.css";

const STEPS = [
  { id: "welcome", title: "Welcome", short: "1. Start" },
  { id: "whatsapp", title: "Connect WhatsApp", short: "2. WhatsApp" },
  { id: "next", title: "You’re ready", short: "3. Finish" },
] as const;

/**
 * Onboarding is a single product gate: connect WhatsApp (Meta). The wizard
 * wraps that in a touch-friendly multi-step shell without extra backend steps.
 * Menu, location and catalogue are finished inside the dashboard after.
 */
export function OnboardingScreen() {
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [hasMeta, setHasMeta] = useState(false);
  const [finishing, setFinishing] = useState(false);

  async function finalizeAndGo() {
    setFinishing(true);
    try {
      await completeOnboarding();
      writeCachedOnboardingComplete(true);
      toast("You're all set. Welcome to your dashboard");
    } catch {
      /* complete gates on Meta; if it races, the router gate still lets them in */
    }
    nav("/menu", { replace: true });
  }

  async function onConnected() {
    setHasMeta(true);
    setStep(2);
    await finalizeAndGo();
  }

  async function refreshStatus() {
    try {
      const st = await fetchOnboardingStatus();
      if (st.has_meta) {
        setHasMeta(true);
        await onConnected();
      }
    } catch {
      setError("Couldn't load your status. Please retry.");
    }
  }

  useEffect(() => {
    refreshStatus().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only status check
  }, []);

  function signOut() {
    logout();
    nav("/login", { replace: true });
  }

  function goBack() {
    setError(null);
    setStep((n) => Math.max(0, n - 1));
  }

  function goContinue() {
    setError(null);
    if (step === 0) {
      setStep(1);
      return;
    }
    if (step === 1) {
      if (!hasMeta) {
        setError("Connect WhatsApp to continue — orders and chats need it.");
        return;
      }
      setStep(2);
      return;
    }
    void finalizeAndGo();
  }

  const current = STEPS[step];

  return (
    <div className={s.screen}>
      <div className={s.shell}>
        <header className={s.top}>
          <div className={s.brand}>
            <span className={s.brandMark}>POS</span>
            <div>
              <strong>Full POS setup</strong>
              <span>A few steps · under 5 minutes</span>
            </div>
          </div>
          <ol className={s.steps} aria-label="Onboarding steps">
            {STEPS.map((st, i) => (
              <li
                key={st.id}
                className={`${s.stepChip} ${i === step ? s.stepActive : ""} ${i < step ? s.stepDone : ""}`}
                aria-current={i === step ? "step" : undefined}
              >
                {st.short}
              </li>
            ))}
          </ol>
        </header>

        <div className={s.body}>
          <aside className={s.rail} aria-hidden={false}>
            <h2 className={s.railTitle}>{current.title}</h2>
            <p className={s.railCopy}>
              {step === 0 &&
                "We’ll connect your restaurant WhatsApp, then open the menu tools so you can take orders."}
              {step === 1 &&
                "Link your Meta / WhatsApp Business account. This is required before live ordering."}
              {step === 2 &&
                "Next inside the dashboard: activate a menu, set delivery location, and invite staff."}
            </p>
            <ul className={s.checklist}>
              <li className={hasMeta ? s.checkDone : undefined}>WhatsApp channel</li>
              <li>Active menu (in dashboard)</li>
              <li>Branch pin &amp; fees (in dashboard)</li>
            </ul>
          </aside>

          <main className={s.panel}>
            {error && (
              <SectionBanner tone="error" onDismiss={() => setError(null)}>
                {error}
              </SectionBanner>
            )}

            {step === 0 && (
              <div className={s.welcome}>
                <h1 className={s.h1}>Set up your POS terminal</h1>
                <p className={s.lead}>
                  Full POS runs delivery and counter work on one surface — WhatsApp ordering,
                  kitchen, riders, and payments.
                </p>
                <div className={s.cards}>
                  <div className={s.infoCard}>
                    <strong>1. WhatsApp</strong>
                    <span>Connect the number customers already message.</span>
                  </div>
                  <div className={s.infoCard}>
                    <strong>2. Menu &amp; location</strong>
                    <span>Finished after this wizard inside Live Ops / Menu.</span>
                  </div>
                  <div className={s.infoCard}>
                    <strong>3. Staff PINs</strong>
                    <span>Add crew under Staff so the PIN pad works at the counter.</span>
                  </div>
                </div>
              </div>
            )}

            {step === 1 && (
              <div className={s.metaStep}>
                <h1 className={s.h1}>Connect WhatsApp</h1>
                <p className={s.lead}>Use Facebook Embedded Signup or enter credentials manually.</p>
                <MetaConnectPanel onSaved={refreshStatus} hideBadge />
              </div>
            )}

            {step === 2 && (
              <div className={s.welcome}>
                <h1 className={s.h1}>You’re ready for the floor</h1>
                <p className={s.lead}>
                  WhatsApp is linked. Open the dashboard to activate a menu and start taking orders.
                </p>
                <div className={s.infoCard}>
                  <strong>Tip</strong>
                  <span>
                    After finish you’ll land on Menu — activate dishes with numbers and prices before
                    New Order.
                  </span>
                </div>
              </div>
            )}
          </main>
        </div>

        <BottomActionBar className={s.footerBar}>
          <Button type="button" variant="ghost" size="lg" onClick={signOut}>
            Sign out
          </Button>
          <div className={s.footerSpacer} />
          <Button type="button" variant="ghost" size="lg" onClick={goBack} disabled={step === 0 || finishing}>
            Back
          </Button>
          <TouchButton type="button" onClick={goContinue} disabled={finishing}>
            {finishing ? "Opening…" : step === 2 ? "Open dashboard" : "Continue"}
          </TouchButton>
        </BottomActionBar>
      </div>
    </div>
  );
}
