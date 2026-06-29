import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { UnifiedMenuPanel } from "../components/UnifiedMenuPanel";
import { toast } from "../components/Toaster";
import { apiClient } from "../lib/apiClient";
import { completeOnboarding, fetchOnboardingStatus } from "../lib/onboardingApi";
import { activateMenu, uploadMenu } from "../lib/menuApi";
import type { MenuWithDiffOut, RestaurantOut } from "../lib/types";
import { DiffPanel } from "../components/DiffPanel";
import s from "./OnboardingScreen.module.css";

type Step = "location" | "menu" | "catalog" | "done";

export function OnboardingScreen() {
  const nav = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [step, setStep] = useState<Step>("location");
  const [lat, setLat] = useState("25.2048");
  const [lng, setLng] = useState("55.2708");
  const [pending, setPending] = useState<MenuWithDiffOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<Awaited<ReturnType<typeof fetchOnboardingStatus>> | null>(null);

  async function refreshStatus() {
    const st = await fetchOnboardingStatus();
    setStatus(st);
    if (st.complete) {
      nav("/menu", { replace: true });
      return;
    }
    if (!st.has_location) setStep("location");
    else if (!st.has_menu) setStep("menu");
    else setStep("catalog");
  }

  useEffect(() => {
    refreshStatus().catch(() => {});
  }, []);

  async function saveLocation() {
    setBusy(true);
    setError(null);
    try {
      await apiClient.patch<RestaurantOut>("/api/v1/me", {
        lat: parseFloat(lat),
        lng: parseFloat(lng),
      });
      toast("Location saved");
      await refreshStatus();
      setStep("menu");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save location");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    try {
      setPending(await uploadMenu(Array.from(files)));
    } catch {
      setError("Menu upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function activateParsedMenu() {
    if (!pending) return;
    setBusy(true);
    try {
      await activateMenu(pending.id);
      setPending(null);
      toast("Menu activated");
      await refreshStatus();
      setStep("catalog");
    } catch {
      setError("Couldn't activate menu");
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      await completeOnboarding();
      toast("You're all set — customers will get your catalogue on WhatsApp");
      nav("/menu", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Complete sync and catalog ID first");
    } finally {
      setBusy(false);
    }
  }

  const steps: { id: Step; label: string; done: boolean }[] = [
    { id: "location", label: "1. Location", done: !!status?.has_location },
    { id: "menu", label: "2. Menu upload", done: !!status?.has_menu },
    { id: "catalog", label: "3. Meta catalogue", done: !!status?.catalog_synced },
  ];

  return (
    <div className={s.screen}>
      <h1 className={s.title}>Set up your restaurant</h1>
      <p className={s.sub}>
        Upload your menu, connect Meta Commerce, and we&apos;ll send customers one catalogue
        when they ask for the menu on WhatsApp.
      </p>

      <div className={s.steps}>
        {steps.map((st) => (
          <span
            key={st.id}
            className={`${s.step} ${step === st.id ? s.stepActive : ""} ${st.done ? s.stepDone : ""}`}
          >
            {st.label}
          </span>
        ))}
      </div>

      {error && <SectionBanner tone="error" onDismiss={() => setError(null)}>{error}</SectionBanner>}

      {pending ? (
        <div className={s.card}>
          <p>Review extracted dishes, then activate.</p>
          {pending.diff_vs_active ? <DiffPanel diff={pending.diff_vs_active} /> : null}
          <div className={s.row}>
            <Button onClick={activateParsedMenu} disabled={busy}>Activate menu</Button>
            <Button variant="ghost" onClick={() => setPending(null)}>Discard</Button>
          </div>
        </div>
      ) : step === "location" ? (
        <div className={s.card}>
          <p className={s.hint}>Pin your restaurant for delivery distance and fees.</p>
          <label className={s.field}>
            <span className="label-upper">Latitude</span>
            <input value={lat} onChange={(e) => setLat(e.target.value)} />
          </label>
          <label className={s.field}>
            <span className="label-upper">Longitude</span>
            <input value={lng} onChange={(e) => setLng(e.target.value)} />
          </label>
          <Button onClick={saveLocation} disabled={busy}>Save &amp; continue</Button>
        </div>
      ) : step === "menu" ? (
        <div className={s.card}>
          <p className={s.hint}>Upload your menu PDF or photos — we extract dishes with AI.</p>
          <input ref={fileRef} type="file" multiple hidden onChange={(e) => onUpload(e.target.files)} />
          <Button onClick={() => fileRef.current?.click()} disabled={busy}>Upload menu</Button>
        </div>
      ) : (
        <div className={s.card}>
          <p className={s.hint}>
            Create a catalogue in Meta Commerce Manager, connect it to WhatsApp, paste the
            Catalog ID, then run Sync both ways. Every text dish must show Linked before
            you finish — unlinked dishes are pushed automatically when the server token is set.
          </p>
          <UnifiedMenuPanel onCatalogIdSaved={refreshStatus} />
          <Button onClick={finish} disabled={busy || !status?.catalog_synced}>
            {busy ? "Finishing…" : "Finish setup"}
          </Button>
        </div>
      )}
    </div>
  );
}