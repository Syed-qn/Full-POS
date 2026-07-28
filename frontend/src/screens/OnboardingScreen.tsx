import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BottomActionBar } from "../components/BottomActionBar";
import { Button, TouchButton } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { LocationPickerModal } from "../components/LocationPickerModal";
import { MetaConnectPanel } from "../components/MetaConnectPanel";
import { toast } from "../components/Toaster";
import { apiClient } from "../lib/apiClient";
import { writeCachedOnboardingComplete } from "../lib/onboardingGate";
import { completeOnboarding, fetchOnboardingStatus } from "../lib/onboardingApi";
import { logout } from "../lib/auth";
import type { RestaurantOut } from "../lib/types";
import s from "./OnboardingScreen.module.css";

/** A restaurant still at the signup default has no usable location. */
function hasPin(lat: number, lng: number): boolean {
  return lat !== 0 || lng !== 0;
}

/**
 * One page, one required thing: where the restaurant is.
 *
 * Signup never asks for coordinates, so a new restaurant starts at 0.0/0.0, a
 * point in the Gulf of Guinea roughly 4,500 km from Dubai. Delivery radius, the
 * fee tiers, batching proximity and rider distances are all measured from it,
 * so every one of them is wrong until it is set. That is why it is the gate.
 *
 * WhatsApp is offered here but optional: it can be connected any time from
 * Settings, and blocking the dashboard on an external Meta signup flow stopped
 * restaurants from doing the setup they CAN finish on their own.
 */
export function OnboardingScreen() {
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [lat, setLat] = useState(0);
  const [lng, setLng] = useState(0);
  const [mapOpen, setMapOpen] = useState(false);
  const [hasMeta, setHasMeta] = useState(false);
  const [finishing, setFinishing] = useState(false);

  useEffect(() => {
    // Prefill from the account that was just created, so the owner confirms
    // rather than retypes.
    apiClient
      .get<RestaurantOut>("/api/v1/me")
      .then((me) => {
        setName(me.name ?? "");
        setLat(Number(me.lat) || 0);
        setLng(Number(me.lng) || 0);
      })
      .catch(() => setError("Couldn't load your restaurant. Please refresh."));
    fetchOnboardingStatus()
      .then((st) => setHasMeta(st.has_meta))
      .catch(() => {});
  }, []);

  function signOut() {
    logout();
    nav("/login", { replace: true });
  }

  function pickLocation(la: number, ln: number) {
    setLat(la);
    setLng(ln);
    setMapOpen(false);
    setError(null);
  }

  async function finish() {
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Restaurant name is required.");
      return;
    }
    if (!hasPin(lat, lng)) {
      setError(
        "Set your restaurant location on the map. Delivery distances are measured from it.",
      );
      return;
    }
    setFinishing(true);
    setError(null);
    try {
      // Save the pin BEFORE completing: the server gates completion on the
      // stored location, so completing first would just be refused.
      await apiClient.patch<RestaurantOut>("/api/v1/me", { name: trimmed, lat, lng });
      await completeOnboarding();
      writeCachedOnboardingComplete(true);
      toast("You're all set. Welcome to your dashboard");
      nav("/", { replace: true });
    } catch {
      setError("Couldn't save your setup. Please try again.");
      setFinishing(false);
    }
  }

  const located = hasPin(lat, lng);

  return (
    <div className={`${s.screen} ${s.singleScreen}`}>
      <div className={`${s.shell} ${s.singleShell}`}>
        <header className={s.top}>
          <div className={s.brand}>
            <span className={s.brandMark}>POS</span>
            <div>
              <strong>Full POS setup</strong>
              <span>One page · about a minute</span>
            </div>
          </div>
        </header>

        <div className={s.single}>
          <main className={s.panel}>
            {error && (
              <SectionBanner tone="error" onDismiss={() => setError(null)}>
                {error}
              </SectionBanner>
            )}

            <h1 className={s.h1}>Set up your restaurant</h1>
            <p className={s.lead}>
              Two details and you're on the floor. Everything else (menu, staff PINs,
              WhatsApp) is set up inside the dashboard whenever you're ready.
            </p>

            <label className={s.field}>
              <span className={s.fieldLabel}>
                Restaurant name <em className={s.req}>required</em>
              </span>
              <input
                aria-label="Restaurant name"
                className={s.input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Biryani House"
              />
            </label>

            <div className={s.field}>
              <span className={s.fieldLabel}>
                Restaurant location <em className={s.req}>required</em>
              </span>
              <div className={s.locCard} data-set={located ? "yes" : "no"}>
                {located ? (
                  <div className={s.locText}>
                    <strong>Location set</strong>
                    <span className={s.locCoords}>
                      {lat.toFixed(5)}, {lng.toFixed(5)}
                    </span>
                  </div>
                ) : (
                  <div className={s.locText}>
                    <strong>No location yet</strong>
                    <span>
                      Delivery radius, fees and rider distances are all measured from this
                      pin.
                    </span>
                  </div>
                )}
                <Button type="button" variant="ghost" onClick={() => setMapOpen(true)}>
                  {located ? "Change on map" : "Set on map"}
                </Button>
              </div>
            </div>

            <div className={s.field}>
              <span className={s.fieldLabel}>
                WhatsApp <em className={s.opt}>optional</em>
              </span>
              <p className={s.optCopy}>
                Connect the number customers message to take WhatsApp orders. You can skip
                this and connect it later under Settings → WhatsApp.
                {hasMeta ? " Already connected." : ""}
              </p>
              <MetaConnectPanel onSaved={() => setHasMeta(true)} hideBadge />
            </div>
          </main>
        </div>

        {mapOpen && (
          <LocationPickerModal
            lat={lat}
            lng={lng}
            onSave={pickLocation}
            onClose={() => setMapOpen(false)}
          />
        )}

        <BottomActionBar className={s.footerBar}>
          <Button type="button" variant="ghost" size="lg" onClick={signOut}>
            Sign out
          </Button>
          <div className={s.footerSpacer} />
          <TouchButton type="button" onClick={finish} disabled={finishing}>
            {finishing ? "Saving…" : "Finish setup"}
          </TouchButton>
        </BottomActionBar>
      </div>
    </div>
  );
}
