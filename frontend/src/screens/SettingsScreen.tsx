import { useEffect, useState } from "react";
import { Button } from "../components/Button";
import { toast } from "../components/Toaster";
import { apiClient } from "../lib/apiClient";
import type { RestaurantOut } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import { LocationPicker } from "../components/LocationPicker";
import s from "./SettingsScreen.module.css";

type Tab = "general" | "fees" | "hours" | "batching" | "dispatch";

const TABS: { key: Tab; label: string; icon: string; desc: string; title: string; blurb: string }[] = [
  { key: "general", label: "General", icon: "🏪", desc: "Profile & location",
    title: "General", blurb: "Your restaurant's name and pickup location." },
  { key: "fees", label: "Delivery Fees", icon: "🛵", desc: "Distance pricing",
    title: "Delivery Fees", blurb: "Charge by delivery distance. Max radius is 10 km." },
  { key: "hours", label: "Opening Hours", icon: "🕒", desc: "When you're open",
    title: "Opening Hours", blurb: "Hours the bot tells customers. Times are Asia/Dubai." },
  { key: "batching", label: "Batching", icon: "📦", desc: "Order grouping",
    title: "Order Batching", blurb: "Limits for grouping orders under the 40-minute SLA." },
  { key: "dispatch", label: "Dispatch & Kitchen", icon: "🧭", desc: "Engine & prep timing",
    title: "Dispatch & Kitchen", blurb: "Routing engine and the distance-driven kitchen plate-by timing." },
];

interface FeeTier {
  max_km: number;
  fee_aed: number;
}

const DEFAULT_TIERS: FeeTier[] = [
  { max_km: 3, fee_aed: 0 },
  { max_km: 5, fee_aed: 5 },
  { max_km: 10, fee_aed: 10 },
];

// Human-readable band a tier actually covers, e.g. "0–3 km · Free" or
// "3–5 km · AED 5". The lower bound is the next-smallest tier below this one
// (0 for the first), computed from the other tiers so it's correct even while
// the rows are still unsorted mid-edit. A 0 fee reads as "Free" to make the
// free band unmistakable (this was the source of confusion).
function tierBandLabel(tier: FeeTier, all: FeeTier[]): string {
  const lower = all
    .map((t) => t.max_km)
    .filter((km) => km < tier.max_km)
    .reduce((mx, km) => Math.max(mx, km), 0);
  const fee = tier.fee_aed === 0 ? "Free" : `AED ${tier.fee_aed}`;
  return `${lower}–${tier.max_km} km · ${fee}`;
}

// Upper limit a manager may set for a tier's distance. The radius = largest
// tier, so this also caps the delivery radius. Spec default is 10 km; raised so
// restaurants with wider coverage can opt in.
const MAX_TIER_KM = 25;

// Opening hours. Index 0=Mon .. 6=Sun (matches backend app.conversation.hours).
interface DayHours {
  open: boolean;
  from: string; // "HH:MM"
  to: string; // "HH:MM"
}

const DAY_LABELS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const DEFAULT_DAY: DayHours = { open: true, from: "10:00", to: "23:00" };

function defaultHours(): DayHours[] {
  return DAY_LABELS.map(() => ({ ...DEFAULT_DAY }));
}

export function SettingsScreen() {
  const [me, setMe] = useState<RestaurantOut | null>(null);
  const [tab, setTab] = useState<Tab>("general");

  // General tab
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");

  // Batching tab
  const [ordersPerBatch, setOrdersPerBatch] = useState(3);
  const [itemsPerOrder, setItemsPerOrder] = useState(20);
  const [maxItemQty, setMaxItemQty] = useState(10);

  // Dispatch & Kitchen tab
  const [dispatchEngine, setDispatchEngine] = useState<"greedy" | "ortools">("greedy");
  const [prepHandling, setPrepHandling] = useState(5);
  const [batchSafety, setBatchSafety] = useState(5);
  const [defaultPrep, setDefaultPrep] = useState(15);
  const [expediteRadius, setExpediteRadius] = useState(1.5);

  // Fees tab
  const [tiers, setTiers] = useState<FeeTier[]>(DEFAULT_TIERS);

  // Hours tab
  const [noFixedHours, setNoFixedHours] = useState(true);
  const [hours, setHours] = useState<DayHours[]>(defaultHours);

  useEffect(() => {
    apiClient.get<RestaurantOut>("/api/v1/me").then((r) => {
      setMe(r);
      setName(r.name);
      setLat(String(r.lat));
      setLng(String(r.lng));
      const sset = r.settings as Record<string, unknown>;
      if (typeof sset.max_orders_per_batch === "number") setOrdersPerBatch(sset.max_orders_per_batch);
      if (typeof sset.max_items_per_order === "number") setItemsPerOrder(sset.max_items_per_order);
      if (typeof sset.max_item_qty === "number") setMaxItemQty(sset.max_item_qty);
      if (sset.dispatch_engine === "ortools" || sset.dispatch_engine === "greedy") setDispatchEngine(sset.dispatch_engine);
      if (typeof sset.prep_handling_minutes === "number") setPrepHandling(sset.prep_handling_minutes);
      if (typeof sset.batch_safety_minutes === "number") setBatchSafety(sset.batch_safety_minutes);
      if (typeof sset.default_prep_minutes === "number") setDefaultPrep(sset.default_prep_minutes);
      if (typeof sset.batch_expedite_radius_km === "number") setExpediteRadius(sset.batch_expedite_radius_km);
      if (Array.isArray(sset.delivery_fee_tiers)) setTiers(sset.delivery_fee_tiers as FeeTier[]);
      // Opening hours: settings.open_hours.days maps "0".."6" -> ["HH:MM","HH:MM"].
      const oh = sset.open_hours as { days?: Record<string, [string, string]> } | undefined;
      const days = oh?.days;
      if (days && Object.keys(days).length > 0) {
        setNoFixedHours(false);
        setHours(
          DAY_LABELS.map((_, i) => {
            const w = days[String(i)];
            return w ? { open: true, from: w[0], to: w[1] } : { ...DEFAULT_DAY, open: false };
          }),
        );
      } else {
        setNoFixedHours(true);
      }
    });
  }, []);

  function flash(err?: string) {
    if (err) { toast(err, "error"); return; }
    toast("Settings saved.", "success");
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
        max_item_qty: maxItemQty,
      });
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  async function saveDispatch() {
    try {
      await apiClient.patch("/api/v1/settings", {
        dispatch_engine: dispatchEngine,
        prep_handling_minutes: prepHandling,
        batch_safety_minutes: batchSafety,
        default_prep_minutes: defaultPrep,
        batch_expedite_radius_km: expediteRadius,
      });
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  async function saveFees() {
    if (tiers.length === 0) { flash("Add at least one fee tier."); return; }
    // Validate: max_km within 1–MAX_TIER_KM (the delivery radius), fee_aed >= 0.
    for (const t of tiers) {
      if (t.max_km <= 0 || t.max_km > MAX_TIER_KM) { flash(`Max km must be between 1 and ${MAX_TIER_KM}.`); return; }
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

  async function saveHours() {
    if (noFixedHours) {
      // Clear hours → backend treats absent days as "always open".
      try {
        await apiClient.patch("/api/v1/settings", { open_hours: { days: {} } });
        flash();
      } catch {
        flash("Failed to save.");
      }
      return;
    }
    const days: Record<string, [string, string]> = {};
    for (let i = 0; i < hours.length; i++) {
      const d = hours[i];
      if (!d.open) continue;
      if (d.to <= d.from) {
        flash(`${DAY_LABELS[i]}: closing time must be after opening time.`);
        return;
      }
      days[String(i)] = [d.from, d.to];
    }
    if (Object.keys(days).length === 0) {
      flash("Mark at least one day open, or choose 'No fixed hours'.");
      return;
    }
    try {
      await apiClient.patch("/api/v1/settings", {
        open_hours: { tz: "Asia/Dubai", days },
      });
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  function updateDay(i: number, patch: Partial<DayHours>) {
    setHours((prev) => prev.map((d, idx) => (idx === i ? { ...d, ...patch } : d)));
  }

  function copyFirstOpenToAll() {
    const template = hours.find((d) => d.open) ?? DEFAULT_DAY;
    setHours((prev) => prev.map((d) => ({ ...d, from: template.from, to: template.to })));
  }

  function updateTier(i: number, field: keyof FeeTier, val: number) {
    // Clamp km to the max allowed radius; fees can't be negative.
    const clamped = field === "max_km" ? Math.min(MAX_TIER_KM, Math.max(0, val)) : Math.max(0, val);
    setTiers((prev) => prev.map((t, idx) => (idx === i ? { ...t, [field]: clamped } : t)));
  }

  function addTier() {
    setTiers((prev) => {
      const lastKm = prev.length ? prev[prev.length - 1].max_km : 0;
      return [...prev, { max_km: Math.min(MAX_TIER_KM, lastKm + 1), fee_aed: 0 }];
    });
  }

  function removeTier(i: number) {
    setTiers((prev) => prev.filter((_, idx) => idx !== i));
  }

  const activeMeta = TABS.find((t) => t.key === tab)!;

  return (
    <div className={s.screen}>
      <PageHeader title="Settings" subtitle="Restaurant profile and delivery rules" />

      <div className={s.layout}>
        <nav className={s.nav} aria-label="Settings sections">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`${s.navItem} ${tab === t.key ? s.navActive : ""}`}
              onClick={() => setTab(t.key)}
              aria-current={tab === t.key}
            >
              <span className={s.navIcon} aria-hidden>{t.icon}</span>
              <span className={s.navText}>
                <span className={s.navLabel}>{t.label}</span>
                <span className={s.navDesc}>{t.desc}</span>
              </span>
            </button>
          ))}
        </nav>

        <div className={s.panel}>
          <header className={s.secHead}>
            <h2 className={s.secTitle}>{activeMeta.title}</h2>
            <p className={s.secBlurb}>{activeMeta.blurb}</p>
          </header>

          {tab === "general" && (
        <div className={s.section}>
          <div className={s.row2}>
            <label className={s.col}>
              <span className={s.rowName}>Restaurant Name</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={255}
                className={s.input}
              />
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Phone (WABA number)</span>
              <input
                type="text"
                value={me?.phone ?? ""}
                disabled
                className={s.input}
                aria-label="Phone (WABA number)"
              />
              <span className={s.rowHint}>🔒 WhatsApp Business number — locked.</span>
            </label>
          </div>
          <div className={s.rowStacked}>
            <div className={s.rowLabel}>
              <span className={s.rowName}>Restaurant Location</span>
              <span className={s.rowHint}>Used to measure delivery distance &amp; fees.</span>
            </div>
            <LocationPicker
              lat={Number(lat)}
              lng={Number(lng)}
              onChange={(la, ln) => { setLat(String(la)); setLng(String(ln)); }}
            />
          </div>
          <div className={s.actions}>
            <Button onClick={saveGeneral}>Save</Button>
          </div>
        </div>
      )}

      {tab === "fees" && (
        <div className={s.section}>
          <div className={s.rowStacked}>
            <div className={s.rowLabel}>
              <span className={s.rowName}>Distance fee tiers</span>
              <span className={s.rowHint}>Each row sets the fee up to that distance — the smallest row starts at 0 km. Set a fee to 0 for free delivery. The largest tier sets your delivery radius (max {MAX_TIER_KM} km).</span>
            </div>
          <div className={s.tierTable}>
            <div className={s.tierHead}>
              <span>Up to (km)</span>
              <span>Fee (AED)</span>
              <span />
            </div>
            {tiers.map((tier, i) => (
              <div key={i} className={s.tierItem}>
                <div className={s.tierRow}>
                  <input
                    type="number"
                    min={1}
                    max={MAX_TIER_KM}
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
                <span className={s.tierBand}>
                  {tierBandLabel(tier, tiers)}
                </span>
              </div>
            ))}
            <button type="button" className={s.addTier} onClick={addTier}>
              + Add tier
            </button>
          </div>
          </div>
          <div className={s.actions}>
            <Button onClick={saveFees}>Save Fee Tiers</Button>
          </div>
        </div>
      )}

      {tab === "hours" && (
        <div className={s.section}>
          <div className={s.rowStacked}>
            <div className={s.rowLabel}>
              <span className={s.rowName}>Availability</span>
              <span className={s.rowHint}>Keep this on to stay always available, or set per-day hours below.</span>
            </div>
            <label className={s.hoursToggle}>
              <input
                type="checkbox"
                checked={noFixedHours}
                onChange={(e) => setNoFixedHours(e.target.checked)}
              />
              <span>No fixed hours (always available)</span>
            </label>
          </div>

          {!noFixedHours && (
            <>
              <div className={s.hoursList}>
                {hours.map((d, i) => (
                  <div key={i} className={s.hourRow}>
                    <label className={s.hourDay}>
                      <input
                        type="checkbox"
                        checked={d.open}
                        onChange={(e) => updateDay(i, { open: e.target.checked })}
                      />
                      <span>{DAY_LABELS[i]}</span>
                    </label>
                    {d.open ? (
                      <div className={s.hourTimes}>
                        <input
                          type="time"
                          value={d.from}
                          onChange={(e) => updateDay(i, { from: e.target.value })}
                          className={s.input}
                          aria-label={`${DAY_LABELS[i]} open`}
                        />
                        <span className={s.hourDash}>–</span>
                        <input
                          type="time"
                          value={d.to}
                          onChange={(e) => updateDay(i, { to: e.target.value })}
                          className={s.input}
                          aria-label={`${DAY_LABELS[i]} close`}
                        />
                      </div>
                    ) : (
                      <span className={s.hourClosed}>Closed</span>
                    )}
                  </div>
                ))}
              </div>
              <button type="button" className={s.addTier} onClick={copyFirstOpenToAll}>
                Copy first open day’s times to all
              </button>
            </>
          )}
          <div className={s.actions}>
            <Button onClick={saveHours}>Save Hours</Button>
          </div>
        </div>
      )}

      {tab === "batching" && (
        <div className={s.section}>
          <div className={s.cardGrid}>
            <label className={s.settingCard}>
              <span className={s.settingIcon}>🛵</span>
              <span className={s.settingName}>Max orders per batch</span>
              <input
                aria-label="orders per batch"
                type="number"
                min={1}
                max={6}
                value={ordersPerBatch}
                onChange={(e) => setOrdersPerBatch(Number(e.target.value))}
                onFocus={(e) => e.target.select()}
                className={`${s.input} ${s.settingInput}`}
              />
              <span className={s.settingHint}>How many orders a rider can carry together.</span>
            </label>
            <label className={s.settingCard}>
              <span className={s.settingIcon}>🧾</span>
              <span className={s.settingName}>Max items per order</span>
              <input
                aria-label="items per order"
                type="number"
                min={1}
                max={100}
                value={itemsPerOrder}
                onChange={(e) => setItemsPerOrder(Number(e.target.value))}
                onFocus={(e) => e.target.select()}
                className={`${s.input} ${s.settingInput}`}
              />
              <span className={s.settingHint}>Upper limit a customer can add to one order.</span>
            </label>
            <label className={`${s.settingCard} ${s.settingCardAccent}`}>
              <span className={s.settingIcon}>🙋</span>
              <span className={s.settingName}>Confirm large quantity above</span>
              <input
                aria-label="max item quantity"
                type="number"
                min={1}
                max={100000}
                value={maxItemQty}
                onChange={(e) => setMaxItemQty(Number(e.target.value))}
                onFocus={(e) => e.target.select()}
                className={`${s.input} ${s.settingInput}`}
              />
              <span className={s.settingHint}>
                If a customer asks for more than this of one item, the bot pauses
                and a human confirms before adding it.
              </span>
            </label>
          </div>
          <div className={s.actions}>
            <Button onClick={saveBatching}>Save</Button>
          </div>
        </div>
      )}

      {tab === "dispatch" && (
        <div className={s.section}>
          <label className={s.col}>
            <span className={s.rowName}>Dispatch engine</span>
            <select
              aria-label="dispatch engine"
              value={dispatchEngine}
              onChange={(e) => setDispatchEngine(e.target.value as "greedy" | "ortools")}
              className={s.input}
            >
              <option value="greedy">Greedy (default) — proximity batching</option>
              <option value="ortools">OR-Tools — SLA-first route optimizer</option>
            </select>
            <span className={s.rowHint}>
              OR-Tools optimizes routes + assignment jointly and drops orders that can't
              make the 40-min SLA (with a manager alert). Pilot per restaurant.
            </span>
          </label>
          <div className={`${s.row2} ${s.row2Compact}`}>
            <label className={s.col}>
              <span className={s.rowName}>Pickup handling (min)</span>
              <input
                aria-label="prep handling minutes" type="number" min={0} max={30}
                value={prepHandling} onChange={(e) => setPrepHandling(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>Slack reserved for the rider hand-off at pickup.</span>
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Batch safety (min)</span>
              <input
                aria-label="batch safety minutes" type="number" min={0} max={30}
                value={batchSafety} onChange={(e) => setBatchSafety(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>Margin so an order that joins a batch still makes the SLA.</span>
            </label>
          </div>
          <div className={`${s.row2} ${s.row2Compact}`}>
            <label className={s.col}>
              <span className={s.rowName}>Default cook time (min)</span>
              <input
                aria-label="default prep minutes" type="number" min={1} max={180}
                value={defaultPrep} onChange={(e) => setDefaultPrep(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>Used for a dish with no prep time set, for the "start by" estimate.</span>
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Batch expedite radius (km)</span>
              <input
                aria-label="batch expedite radius km" type="number" min={0.1} max={10} step={0.1}
                value={expediteRadius} onChange={(e) => setExpediteRadius(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>Nudge the kitchen to rush a cooking order within this distance of a run going out.</span>
            </label>
          </div>
          <div className={s.actions}>
            <Button onClick={saveDispatch}>Save</Button>
          </div>
        </div>
      )}
        </div>
      </div>
    </div>
  );
}
