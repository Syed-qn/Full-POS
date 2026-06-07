import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { SectionBanner } from "../components/SectionBanner";
import { apiClient } from "../lib/apiClient";
import type { RestaurantOut } from "../lib/types";
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

  // Batching tab
  const [ordersPerBatch, setOrdersPerBatch] = useState(3);
  const [itemsPerOrder, setItemsPerOrder] = useState(20);

  // Fees tab
  const [tiers, setTiers] = useState<FeeTier[]>(DEFAULT_TIERS);

  useEffect(() => {
    apiClient.get<RestaurantOut>("/api/v1/me").then((r) => {
      setMe(r);
      setName(r.name);
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
    try {
      const updated = await apiClient.patch<RestaurantOut>("/api/v1/me", { name: name.trim() });
      setMe(updated);
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
    // Validate: tiers must be ascending by max_km, fee_aed >= 0
    for (const t of tiers) {
      if (t.max_km <= 0 || t.max_km > 10) { flash("Max km must be 1–10."); return; }
      if (t.fee_aed < 0) { flash("Fee cannot be negative."); return; }
    }
    try {
      await apiClient.patch("/api/v1/settings", { delivery_fee_tiers: tiers });
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  function updateTier(i: number, field: keyof FeeTier, val: number) {
    setTiers((prev) => prev.map((t, idx) => idx === i ? { ...t, [field]: val } : t));
  }

  return (
    <div className={s.screen}>
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
            </div>
            {tiers.map((tier, i) => (
              <div key={i} className={s.tierRow}>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={tier.max_km}
                  onChange={(e) => updateTier(i, "max_km", Number(e.target.value))}
                  className={s.input}
                />
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={tier.fee_aed}
                  onChange={(e) => updateTier(i, "fee_aed", Number(e.target.value))}
                  className={s.input}
                />
              </div>
            ))}
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
              className={s.input}
            />
          </label>
          <Button onClick={saveBatching}>Save</Button>
        </div>
      )}
    </div>
  );
}
