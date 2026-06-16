import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { apiClient } from "../lib/apiClient";
import type { RestaurantOut } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import s from "./SettingsScreen.module.css";

type Tab = "general" | "fees" | "batching";

interface FeeTier {
  max_km: number;
  fee_aed: number;
}

const DEFAULT_TIERS: FeeTier[] = [
  { max_km: 3, fee_aed: 0 },
  { max_km: 5, fee_aed: 5 },
  { max_km: 10, fee_aed: 10 },
];

export function SettingsScreen() {
  const [me, setMe] = useState<RestaurantOut | null>(null);
  const [tab, setTab] = useState<Tab>("general");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // General tab
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");

  // Batching tab
  const [ordersPerBatch, setOrdersPerBatch] = useState(3);
  const [itemsPerOrder, setItemsPerOrder] = useState(20);

  // Fees tab
  const [tiers, setTiers] = useState<FeeTier[]>(DEFAULT_TIERS);

  useEffect(() => {
    apiClient.get<RestaurantOut>("/api/v1/me").then((r) => {
      setMe(r);
      setName(r.name);
      setLat(String(r.lat));
      setLng(String(r.lng));
      const sset = r.settings as Record<string, unknown>;
      if (typeof sset.max_orders_per_batch === "number") setOrdersPerBatch(sset.max_orders_per_batch);
      if (typeof sset.max_items_per_order === "number") setItemsPerOrder(sset.max_items_per_order);
      if (Array.isArray(sset.delivery_fee_tiers)) setTiers(sset.delivery_fee_tiers as FeeTier[]);
    });
  }, []);

  function flash(err?: string) {
    if (err) { setError(err); return; }
    setError(null);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  }

  async function saveGeneral() {
    if (!name.trim()) return;
    const latNum = Number(lat);
    const lngNum = Number(lng);
    if (lat.trim() === "" || Number.isNaN(latNum) || latNum < -90 || latNum > 90) {
      flash("Latitude must be between -90 and 90.");
      return;
    }
    if (lng.trim() === "" || Number.isNaN(lngNum) || lngNum < -180 || lngNum > 180) {
      flash("Longitude must be between -180 and 180.");
      return;
    }
    try {
      const updated = await apiClient.patch<RestaurantOut>("/api/v1/me", {
        name: name.trim(),
        lat: latNum,
        lng: lngNum,
      });
      setMe(updated);
      setLat(String(updated.lat));
      setLng(String(updated.lng));
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  async function saveBatching() {
    try {
      await apiClient.patch("/api/v1/settings", {
        max_orders_per_batch: ordersPerBatch,
        max_items_per_order: itemsPerOrder,
      });
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  async function saveFees() {
    if (tiers.length === 0) { flash("Add at least one fee tier."); return; }
    // Validate: max_km within 1–10 (the delivery radius), fee_aed >= 0.
    for (const t of tiers) {
      if (t.max_km <= 0 || t.max_km > 10) { flash("Max km must be between 1 and 10."); return; }
      if (t.fee_aed < 0) { flash("Fee cannot be negative."); return; }
    }
    const kms = tiers.map((t) => t.max_km);
    if (new Set(kms).size !== kms.length) { flash("Each tier needs a unique 'up to km'."); return; }
    // Persist ascending by distance so the matcher picks the right tier.
    const sorted = [...tiers].sort((a, b) => a.max_km - b.max_km);
    try {
      await apiClient.patch("/api/v1/settings", { delivery_fee_tiers: sorted });
      setTiers(sorted);
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  function updateTier(i: number, field: keyof FeeTier, val: number) {
    // Clamp km to the 10 km radius; fees can't be negative.
    const clamped = field === "max_km" ? Math.min(10, Math.max(0, val)) : Math.max(0, val);
    setTiers((prev) => prev.map((t, idx) => (idx === i ? { ...t, [field]: clamped } : t)));
  }

  function addTier() {
    setTiers((prev) => {
      const lastKm = prev.length ? prev[prev.length - 1].max_km : 0;
      return [...prev, { max_km: Math.min(10, lastKm + 1), fee_aed: 0 }];
    });
  }

  function removeTier(i: number) {
    setTiers((prev) => prev.filter((_, idx) => idx !== i));
  }

  return (
    <div className={s.screen}>
      <PageHeader title="Settings" subtitle="Restaurant profile and delivery rules" />
      <div className={s.tabs}>
        {(["general", "fees", "batching"] as Tab[]).map((t) => (
          <button key={t} className={`${s.tab} ${tab === t ? s.active : ""}`} onClick={() => { setTab(t); setSaved(false); setError(null); }}>
            {t}
          </button>
        ))}
      </div>

      {saved && <SectionBanner tone="success">Settings saved.</SectionBanner>}
      {error && <SectionBanner tone="warning">{error}</SectionBanner>}

      {tab === "general" && (
        <div className={s.section}>
          <label className={s.field}>
            <span className="label-upper">Restaurant Name</span>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={255}
              className={s.input}
            />
          </label>
          <div className={s.fieldReadonly}>
            <span className="label-upper">Phone (WABA number)</span>
            <span className={s.readonlyValue}>{me?.phone ?? "—"}</span>
            <span className={s.hint}>WhatsApp Business Account number — cannot be changed here.</span>
          </div>
          <div className={s.field}>
            <span className="label-upper">Restaurant Location</span>
            <div className={s.latLngRow}>
              <input
                type="number"
                step="any"
                value={lat}
                onChange={(e) => setLat(e.target.value)}
                onFocus={(e) => e.target.select()}
                placeholder="Latitude (e.g. 25.1124)"
                className={s.input}
                aria-label="latitude"
              />
              <input
                type="number"
                step="any"
                value={lng}
                onChange={(e) => setLng(e.target.value)}
                onFocus={(e) => e.target.select()}
                placeholder="Longitude (e.g. 55.1390)"
                className={s.input}
                aria-label="longitude"
              />
            </div>
            <span className={s.hint}>Used to measure delivery distance &amp; fees. Tip: in Google Maps, right-click your restaurant → the first row copies the lat, lng.</span>
          </div>
          <Button onClick={saveGeneral}>Save</Button>
        </div>
      )}

      {tab === "fees" && (
        <div className={s.section}>
          <p className={s.note}>
            Fee tiers apply per delivery distance. Max radius is 10 km — addresses beyond are rejected automatically.
          </p>
          <div className={s.tierTable}>
            <div className={s.tierHead}>
              <span>Up to (km)</span>
              <span>Fee (AED)</span>
              <span />
            </div>
            {tiers.map((tier, i) => (
              <div key={i} className={s.tierRow}>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={tier.max_km}
                  onChange={(e) => updateTier(i, "max_km", Number(e.target.value))}
                  onFocus={(e) => e.target.select()}
                  className={s.input}
                />
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={tier.fee_aed}
                  onChange={(e) => updateTier(i, "fee_aed", Number(e.target.value))}
                  onFocus={(e) => e.target.select()}
                  className={s.input}
                />
                <button
                  type="button"
                  className={s.tierRemove}
                  onClick={() => removeTier(i)}
                  aria-label="Remove tier"
                  title="Remove tier"
                >
                  ×
                </button>
              </div>
            ))}
            <button type="button" className={s.addTier} onClick={addTier}>
              + Add tier
            </button>
          </div>
          <Button onClick={saveFees}>Save Fee Tiers</Button>
        </div>
      )}

      {tab === "batching" && (
        <div className={s.section}>
          <label className={s.field}>
            <span className="label-upper">Max orders per batch</span>
            <input
              aria-label="orders per batch"
              type="number"
              min={1}
              max={6}
              value={ordersPerBatch}
              onChange={(e) => setOrdersPerBatch(Number(e.target.value))}
              onFocus={(e) => e.target.select()}
              className={s.input}
            />
          </label>
          <label className={s.field}>
            <span className="label-upper">Max items per order</span>
            <input
              aria-label="items per order"
              type="number"
              min={1}
              max={100}
              value={itemsPerOrder}
              onChange={(e) => setItemsPerOrder(Number(e.target.value))}
              onFocus={(e) => e.target.select()}
              className={s.input}
            />
          </label>
          <Button onClick={saveBatching}>Save</Button>
        </div>
      )}
    </div>
  );
}
