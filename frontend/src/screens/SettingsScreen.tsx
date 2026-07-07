import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { toast } from "../components/Toaster";
import { apiClient } from "../lib/apiClient";
import { disconnectMeta, resubscribeMeta } from "../lib/onboardingApi";
import { writeCachedOnboardingComplete } from "../lib/onboardingGate";
import {
  createApiKey,
  listApiKeys,
  revokeApiKey,
  type ApiKey,
} from "../lib/partnerApi";
import type { LoyaltyConfig, LoyaltyTierThreshold, RestaurantOut } from "../lib/types";
import {
  deletePaymentCredentials,
  getPaymentCredentials,
  setPaymentCredentials,
  type CredentialsStatus,
} from "../lib/paymentsApi";
import { PageHeader } from "../components/PageHeader";
import { LocationPicker, reverseGeocode } from "../components/LocationPicker";
import { ConfirmDialog } from "../components/ConfirmDialog";
import s from "./SettingsScreen.module.css";

type Tab = "general" | "fees" | "hours" | "batching" | "cart" | "resale" | "loyalty" | "dispatch" | "integrations" | "payments";

interface ResaleConfig {
  enabled: boolean;
  discount_type: "percent" | "fixed";
  discount_value: number;
  max_age_minutes: number;
}

const DEFAULT_RESALE: ResaleConfig = {
  enabled: true,
  discount_type: "percent",
  discount_value: 30,
  max_age_minutes: 30,
};

const TABS: { key: Tab; label: string; icon: string; desc: string; title: string; blurb: string }[] = [
  { key: "general", label: "General", icon: "🏪", desc: "Profile & location",
    title: "General", blurb: "Your restaurant's name and pickup location." },
  { key: "fees", label: "Delivery Fees", icon: "🛵", desc: "Distance pricing",
    title: "Delivery Fees", blurb: "Charge by delivery distance. Max radius is 10 km." },
  { key: "hours", label: "Opening Hours", icon: "🕒", desc: "When you're open",
    title: "Opening Hours", blurb: "Hours the bot tells customers. Times are Asia/Dubai." },
  { key: "batching", label: "Batching", icon: "📦", desc: "Order grouping",
    title: "Batching", blurb: "Limits for grouping orders under the 40-minute SLA." },
  { key: "cart", label: "Cart recovery", icon: "🛒", desc: "Abandoned carts",
    title: "Cart recovery", blurb: "Remind customers who left items in their cart, and auto-clear stale carts." },
  { key: "resale", label: "Resale", icon: "⚡", desc: "Cancelled food",
    title: "Cancelled-order resale", blurb: "When the kitchen has already started an order that gets cancelled, offer the cooked food to the next customer at a discount — fast delivery, batched with anything else they order." },
  { key: "loyalty", label: "Loyalty", icon: "🎁", desc: "Tiers & rewards",
    title: "Loyalty", blurb: "Reward repeat customers with earned credit and tier-based perks. Everything here is yours to tune." },
  { key: "dispatch", label: "Dispatch & Kitchen", icon: "🧭", desc: "Engine & prep timing",
    title: "Dispatch & Kitchen", blurb: "Routing engine and the distance-driven kitchen plate-by timing." },
  { key: "integrations", label: "API Keys", icon: "🔑", desc: "Partner access",
    title: "Partner API Keys", blurb: "Issue keys so a partner system (e.g. a POS) can pull your data read-only." },
  { key: "payments", label: "Payments", icon: "💳", desc: "Card processor",
    title: "Payment Processing", blurb: "Connect your own Stripe account to accept card payments. Without one, card charges run in test/mock mode." },
];

// "Max items per order" isn't enforced by the backend yet — hidden until it is.
// Flip to true to re-expose the control (it's still loaded + saved underneath).
const SHOW_MAX_ITEMS_PER_ORDER = false;

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

// Sensible defaults for older restaurant rows that predate the loyalty config.
// Everything stays editable in the UI — these are only the starting values.
const DEFAULT_LOYALTY: LoyaltyConfig = {
  enabled: false,
  earn_rate: 0.05,
  earn_max_per_order_aed: 20,
  credit_ttl_days: 90,
  tiers: {
    gold: { min_orders: 5, min_spend_aed: 300, max_recency_days: 30 },
    silver: { min_orders: 3, min_spend_aed: 120, max_recency_days: 60 },
    bronze: { min_orders: 2, min_spend_aed: 0, max_recency_days: 90 },
  },
  tier_rewards: {
    gold: { discount_aed: 25, every_n_orders: 5 },
    silver: { discount_aed: 10, every_n_orders: 6 },
    bronze: null,
  },
  demotion_grace_days: 30,
  scope_includes_catalog: true,
};

const LOYALTY_TIERS = ["gold", "silver", "bronze"] as const;
type LoyaltyTierKey = (typeof LOYALTY_TIERS)[number];
const TIER_LABELS: Record<LoyaltyTierKey, string> = {
  gold: "🥇 Gold",
  silver: "🥈 Silver",
  bronze: "🥉 Bronze",
};

// Dispatch presets — design §8.2. Buttons apply values to form state only (save separately).
const DISPATCH_PRESETS = {
  slaSafe: {
    dispatch_engine: "ortools",
    batch_proximity_km: 1.5,
    batch_max_detour_km: 0.5,
    batch_hold_seconds: 120,
    sla_buffer_per_order_minutes: 10,
  },
  dense: {
    dispatch_engine: "ortools",
    batch_proximity_km: 2.0,
    batch_max_detour_km: 0.8,
    batch_hold_seconds: 150,
    sla_buffer_per_order_minutes: 10,
  },
  suburban: {
    dispatch_engine: "ortools",
    batch_proximity_km: 3.0,
    batch_max_detour_km: 1.5,
    batch_hold_seconds: 120,
    sla_buffer_per_order_minutes: 10,
  },
  conservative: {
    dispatch_engine: "greedy",
    batch_proximity_km: 1.0,
    batch_max_detour_km: 0,
    batch_hold_seconds: 0,
    sla_buffer_per_order_minutes: 10,
  },
} as const;

type DispatchPresetKey = keyof typeof DISPATCH_PRESETS;

type DeliveryZone = {
  name: string;
  center_lat: number;
  center_lng: number;
  radius_km: number;
};

const DISPATCH_PRESET_BUTTONS: {
  key: DispatchPresetKey;
  label: string;
  hint: string;
}[] = [
  {
    key: "slaSafe",
    label: "SLA-safe launch",
    hint: "OR-Tools with tight geometry — recommended default for new restaurants.",
  },
  {
    key: "dense",
    label: "Dense city",
    hint: "Wider grouping for high-density areas; use after a week of on-time delivery.",
  },
  {
    key: "suburban",
    label: "Suburban",
    hint: "Larger proximity and detour for spread-out delivery zones.",
  },
  {
    key: "conservative",
    label: "Conservative",
    hint: "Legacy greedy routing — instant rollback if SLA regresses.",
  },
];

function defaultHours(): DayHours[] {
  return DAY_LABELS.map(() => ({ ...DEFAULT_DAY }));
}

export function SettingsScreen() {
  const nav = useNavigate();
  const [me, setMe] = useState<RestaurantOut | null>(null);
  const [tab, setTab] = useState<Tab>("general");

  // General tab
  const [name, setName] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [trn, setTrn] = useState("");
  const [mapOpen, setMapOpen] = useState(false);
  const [locAddress, setLocAddress] = useState<string | null>(null);
  // WhatsApp disconnect
  const [showDisconnect, setShowDisconnect] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [resubscribing, setResubscribing] = useState(false);

  async function onResubscribeWhatsApp() {
    setResubscribing(true);
    try {
      await resubscribeMeta();
      toast("WhatsApp webhooks re-subscribed — send a test message now.", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Re-subscribe failed", "error");
    } finally {
      setResubscribing(false);
    }
  }

  async function onDisconnectWhatsApp() {
    setDisconnecting(true);
    try {
      await disconnectMeta();
      // Onboarding gate must re-trigger — force a re-onboard on next route check.
      writeCachedOnboardingComplete(false);
      toast("WhatsApp disconnected — reconnect to keep operating");
      nav("/onboarding", { replace: true });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't disconnect");
      setDisconnecting(false);
      setShowDisconnect(false);
    }
  }

  // Batching tab
  const [ordersPerBatch, setOrdersPerBatch] = useState(3);
  // Max items per order — kept wired (loaded + saved) but its UI card is hidden for
  // now; flip SHOW_MAX_ITEMS_PER_ORDER back on to re-expose it.
  const [itemsPerOrder, setItemsPerOrder] = useState(20);
  const [maxItemQty, setMaxItemQty] = useState(10);

  // Dispatch & Kitchen tab
  const [dispatchEngine, setDispatchEngine] = useState<"greedy" | "ortools">("greedy");
  const [defaultPrep, setDefaultPrep] = useState(15);
  const [expediteRadius, setExpediteRadius] = useState(1.5);
  // Greedy batching geometry
  const [batchProximity, setBatchProximity] = useState(1.0);
  const [maxDetour, setMaxDetour] = useState(0); // 0 = corridor off
  const [holdSeconds, setHoldSeconds] = useState(0); // 0 = batch hold window off
  const [slaBuffer, setSlaBuffer] = useState(10);
  const [prepLeadMin, setPrepLeadMin] = useState(8);
  const [deliveryZones, setDeliveryZones] = useState<DeliveryZone[]>([]);

  // Cart recovery tab
  const [cartReminder, setCartReminder] = useState(true);
  const [cartRecoveryMin, setCartRecoveryMin] = useState(15);
  const [cartExpiryMin, setCartExpiryMin] = useState(60);

  // Resale tab — cancelled-after-cooking fast offers
  const [resale, setResale] = useState<ResaleConfig>(DEFAULT_RESALE);

  // Loyalty tab — full config object (everything editable per restaurant)
  const [loyalty, setLoyalty] = useState<LoyaltyConfig>(DEFAULT_LOYALTY);

  // Fees tab
  const [tiers, setTiers] = useState<FeeTier[]>(DEFAULT_TIERS);

  // Hours tab
  const [noFixedHours, setNoFixedHours] = useState(true);
  const [hours, setHours] = useState<DayHours[]>(defaultHours);

  // Reverse-geocode the saved coordinates so the summary shows a real address.
  useEffect(() => {
    const la = Number(lat), ln = Number(lng);
    if (!Number.isFinite(la) || !Number.isFinite(ln) || (la === 0 && ln === 0) || lat === "" || lng === "") {
      setLocAddress(null);
      return;
    }
    let cancelled = false;
    const t = setTimeout(() => {
      reverseGeocode(la, ln)
        .then((a) => { if (!cancelled) setLocAddress(a); })
        .catch(() => { if (!cancelled) setLocAddress(null); });
    }, 400);
    return () => { cancelled = true; clearTimeout(t); };
  }, [lat, lng]);

  useEffect(() => {
    apiClient.get<RestaurantOut>("/api/v1/me").then((r) => {
      setMe(r);
      setName(r.name);
      setLat(String(r.lat));
      setLng(String(r.lng));
      const sset = r.settings as Record<string, unknown>;
      if (typeof sset.trn === "string") setTrn(sset.trn);
      if (typeof sset.max_orders_per_batch === "number") setOrdersPerBatch(sset.max_orders_per_batch);
      if (typeof sset.max_items_per_order === "number") setItemsPerOrder(sset.max_items_per_order);
      if (typeof sset.max_item_qty === "number") setMaxItemQty(sset.max_item_qty);
      if (sset.dispatch_engine === "ortools" || sset.dispatch_engine === "greedy") setDispatchEngine(sset.dispatch_engine);
      if (typeof sset.default_prep_minutes === "number") setDefaultPrep(sset.default_prep_minutes);
      if (typeof sset.batch_expedite_radius_km === "number") setExpediteRadius(sset.batch_expedite_radius_km);
      if (typeof sset.batch_proximity_km === "number") setBatchProximity(sset.batch_proximity_km);
      if (typeof sset.batch_max_detour_km === "number") setMaxDetour(sset.batch_max_detour_km);
      if (typeof sset.batch_hold_seconds === "number") setHoldSeconds(sset.batch_hold_seconds);
      if (typeof sset.sla_buffer_per_order_minutes === "number") setSlaBuffer(sset.sla_buffer_per_order_minutes);
      if (typeof sset.prep_dispatch_lead_min === "number") setPrepLeadMin(sset.prep_dispatch_lead_min);
      if (Array.isArray(sset.delivery_zones)) {
        setDeliveryZones(
          (sset.delivery_zones as DeliveryZone[]).map((z) => ({
            name: String(z.name ?? ""),
            center_lat: Number(z.center_lat ?? 0),
            center_lng: Number(z.center_lng ?? 0),
            radius_km: Number(z.radius_km ?? 1),
          })),
        );
      }
      if (typeof sset.cart_reminder_enabled === "boolean") setCartReminder(sset.cart_reminder_enabled);
      if (typeof sset.cart_recovery_minutes === "number") setCartRecoveryMin(sset.cart_recovery_minutes);
      if (typeof sset.cart_expiry_minutes === "number") setCartExpiryMin(sset.cart_expiry_minutes);
      const rset = sset.resale as Partial<ResaleConfig> | undefined;
      if (rset && typeof rset === "object") {
        setResale({ ...DEFAULT_RESALE, ...rset });
      }
      if (Array.isArray(sset.delivery_fee_tiers)) setTiers(sset.delivery_fee_tiers as FeeTier[]);
      // Loyalty: deep-merge stored config over defaults so older rows / partial
      // configs still render every editable field.
      const lset = sset.loyalty as Partial<LoyaltyConfig> | undefined;
      if (lset && typeof lset === "object") {
        setLoyalty({
          ...DEFAULT_LOYALTY,
          ...lset,
          tiers: { ...DEFAULT_LOYALTY.tiers, ...(lset.tiers ?? {}) },
          tier_rewards: { ...DEFAULT_LOYALTY.tier_rewards, ...(lset.tier_rewards ?? {}) },
        });
      }
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
      const withTrn = await apiClient.patch<RestaurantOut>("/api/v1/settings", {
        trn: trn.trim(),
      });
      setMe(withTrn);
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

  async function saveCart() {
    try {
      await apiClient.patch("/api/v1/settings", {
        cart_reminder_enabled: cartReminder,
        cart_recovery_minutes: cartRecoveryMin,
        cart_expiry_minutes: cartExpiryMin,
      });
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  async function saveResale() {
    try {
      await apiClient.patch("/api/v1/settings", { resale });
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  async function saveLoyalty() {
    try {
      await apiClient.patch("/api/v1/settings", { loyalty });
      flash();
    } catch {
      flash("Failed to save.");
    }
  }

  // Helpers to update nested loyalty config immutably.
  function setLoyaltyField<K extends keyof LoyaltyConfig>(key: K, value: LoyaltyConfig[K]) {
    setLoyalty((l) => ({ ...l, [key]: value }));
  }
  function setTierField(tier: LoyaltyTierKey, field: keyof LoyaltyTierThreshold, value: number) {
    setLoyalty((l) => ({ ...l, tiers: { ...l.tiers, [tier]: { ...l.tiers[tier], [field]: value } } }));
  }
  function setRewardField(tier: LoyaltyTierKey, field: "discount_aed" | "every_n_orders", value: number) {
    setLoyalty((l) => {
      const cur = l.tier_rewards[tier] ?? { discount_aed: 0, every_n_orders: 0 };
      return { ...l, tier_rewards: { ...l.tier_rewards, [tier]: { ...cur, [field]: value } } };
    });
  }

  function applyDispatchPreset(key: DispatchPresetKey) {
    const p = DISPATCH_PRESETS[key];
    setDispatchEngine(p.dispatch_engine);
    setBatchProximity(p.batch_proximity_km);
    setMaxDetour(p.batch_max_detour_km);
    setHoldSeconds(p.batch_hold_seconds);
    setSlaBuffer(p.sla_buffer_per_order_minutes);
  }

  function addDeliveryZone() {
    setDeliveryZones((zones) => [
      ...zones,
      { name: `Zone ${zones.length + 1}`, center_lat: Number(lat) || 25.2, center_lng: Number(lng) || 55.2, radius_km: 2.5 },
    ]);
  }

  function updateDeliveryZone(index: number, patch: Partial<DeliveryZone>) {
    setDeliveryZones((zones) =>
      zones.map((z, i) => (i === index ? { ...z, ...patch } : z)),
    );
  }

  function removeDeliveryZone(index: number) {
    setDeliveryZones((zones) => zones.filter((_, i) => i !== index));
  }

  async function saveDispatch() {
    for (const z of deliveryZones) {
      if (!z.name.trim()) {
        flash("Each delivery zone needs a name.");
        return;
      }
      if (z.radius_km <= 0 || z.radius_km > 10) {
        flash("Zone radius must be between 0.1 and 10 km.");
        return;
      }
    }
    try {
      await apiClient.patch("/api/v1/settings", {
        dispatch_engine: dispatchEngine,
        default_prep_minutes: defaultPrep,
        prep_dispatch_lead_min: prepLeadMin,
        batch_expedite_radius_km: expediteRadius,
        batch_proximity_km: batchProximity,
        batch_max_detour_km: maxDetour,
        batch_hold_seconds: holdSeconds,
        sla_buffer_per_order_minutes: slaBuffer,
        delivery_zones: deliveryZones,
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

          {me === null ? (
            <SettingsSkeleton />
          ) : (
          <>
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
              <span className={s.rowName}>TRN (Tax Registration Number)</span>
              <input
                type="text"
                value={trn}
                onChange={(e) => setTrn(e.target.value)}
                maxLength={32}
                placeholder="100123456700003"
                className={s.input}
              />
              <span className={s.rowHint}>Printed on tax invoices. Leave blank if not VAT-registered.</span>
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
              <span className={s.rowHint}>🔒 WhatsApp Business number, locked.</span>
            </label>
          </div>
          <div className={s.rowStacked}>
            <div className={s.locHead}>
              <div className={s.rowLabel}>
                <span className={s.rowName}>Restaurant Location</span>
                <span className={s.rowHint}>Used to measure delivery distance &amp; fees.</span>
              </div>
              <button
                type="button"
                className={s.locToggle}
                aria-expanded={mapOpen}
                onClick={() => setMapOpen((o) => !o)}
              >
                {mapOpen ? "Close map" : "Set on map"}
              </button>
            </div>
            <div className={s.locCurrent}>
              <span className={s.locPin} aria-hidden="true">📍</span>
              {lat.trim() && lng.trim() ? (
                <div className={s.locTextWrap}>
                  <span className={s.locAddr}>{locAddress ?? "Resolving address…"}</span>
                  <span className={s.locCoords}>Lat, Long: {Number(lat).toFixed(5)}, {Number(lng).toFixed(5)}</span>
                </div>
              ) : (
                <span className={s.rowHint}>No location set yet. Open the map to set it.</span>
              )}
            </div>
            {mapOpen && (
              <LocationPicker
                lat={Number(lat)}
                lng={Number(lng)}
                onChange={(la, ln) => { setLat(String(la)); setLng(String(ln)); }}
              />
            )}
          </div>
          <div className={s.actions}>
            <Button onClick={saveGeneral}>Save</Button>
          </div>

          <div
            className={s.rowStacked}
            style={{ marginTop: 24, borderTop: "1px solid var(--border, #334155)", paddingTop: 18 }}
          >
            <div className={s.rowLabel}>
              <span className={s.rowName}>WhatsApp connection</span>
              <span className={s.rowHint}>
                Disconnect this restaurant's WhatsApp (Meta) account. You'll be taken
                to onboarding to reconnect. Your menu, orders and settings are kept —
                but the bot stops replying until you reconnect.
              </span>
            </div>
            <div className={s.actions}>
              <Button
                onClick={onResubscribeWhatsApp}
                disabled={resubscribing}
              >
                {resubscribing ? "Re-subscribing…" : "Fix inbound (re-subscribe)"}
              </Button>
              <Button variant="ghost" onClick={() => setShowDisconnect(true)}>
                Disconnect WhatsApp
              </Button>
            </div>
          </div>
        </div>
      )}

      {tab === "fees" && (
        <div className={s.section}>
          <div className={s.rowStacked}>
            <div className={s.rowLabel}>
              <span className={s.rowName}>Distance fee tiers</span>
              <span className={s.rowHint}>Each row sets the fee up to that distance. The smallest row starts at 0 km. Set a fee to 0 for free delivery. The largest tier sets your delivery radius (max {MAX_TIER_KM} km).</span>
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
          <div className={`${s.row2} ${s.row2Compact}`}>
            <label className={s.col}>
              <span className={s.rowName}>Max orders per rider</span>
              <input
                aria-label="orders per batch" type="number" min={1} max={6}
                value={ordersPerBatch} onChange={(e) => setOrdersPerBatch(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>
                Most orders one rider carries in a single trip. Extra ready orders go to
                the next rider. For example, set 3, and if 5 are ready one rider takes 3 and
                another takes 2.
              </span>
            </label>
            {SHOW_MAX_ITEMS_PER_ORDER && (
              <label className={s.col}>
                <span className={s.rowName}>Max items per order</span>
                <input
                  aria-label="items per order" type="number" min={1} max={100}
                  value={itemsPerOrder} onChange={(e) => setItemsPerOrder(Number(e.target.value))}
                  onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
                />
                <span className={s.rowHint}>Upper limit a customer can add to one order.</span>
              </label>
            )}
            <label className={s.col}>
              <span className={s.rowName}>Confirm large quantity above</span>
              <input
                aria-label="max item quantity" type="number" min={1} max={100000}
                value={maxItemQty} onChange={(e) => setMaxItemQty(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>
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

      {tab === "resale" && (
        <div className={s.section}>
          <div className={s.rowStacked}>
            <div className={s.rowLabel}>
              <span className={s.rowName}>Offer cancelled-but-cooked food</span>
              <span className={s.rowHint}>
                When a customer cancels after the kitchen has started cooking, the food is
                pitched to the next customer in chat as a fast, discounted delivery. The
                rider is re-routed to the new address; extra dishes the buyer orders are
                batched into the same trip.
              </span>
            </div>
            <label className={s.hoursToggle}>
              <input
                type="checkbox"
                checked={resale.enabled}
                onChange={(e) => setResale((r) => ({ ...r, enabled: e.target.checked }))}
              />
              <span>Enable resale offers</span>
            </label>
          </div>
          <div className={`${s.row2} ${s.row2Compact}`}>
            <label className={s.col}>
              <span className={s.rowName}>Discount type</span>
              <select
                aria-label="resale discount type"
                className={s.input}
                value={resale.discount_type}
                onChange={(e) =>
                  setResale((r) => ({
                    ...r,
                    discount_type: e.target.value as "percent" | "fixed",
                  }))
                }
              >
                <option value="percent">Percent (%)</option>
                <option value="fixed">Fixed amount (AED)</option>
              </select>
            </label>
            <label className={s.col}>
              <span className={s.rowName}>
                {resale.discount_type === "percent" ? "Discount (%)" : "Discount (AED)"}
              </span>
              <input
                aria-label="resale discount value"
                type="number"
                min={0}
                max={resale.discount_type === "percent" ? 100 : undefined}
                value={resale.discount_value}
                onChange={(e) =>
                  setResale((r) => ({ ...r, discount_value: Number(e.target.value) }))
                }
                onFocus={(e) => e.target.select()}
                className={`${s.input} ${s.inputNum}`}
              />
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Max age (minutes)</span>
              <input
                aria-label="resale max age minutes"
                type="number"
                min={1}
                max={240}
                value={resale.max_age_minutes}
                onChange={(e) =>
                  setResale((r) => ({ ...r, max_age_minutes: Number(e.target.value) }))
                }
                onFocus={(e) => e.target.select()}
                className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>Don't offer food cancelled longer ago than this.</span>
            </label>
          </div>
          <div className={s.actions}>
            <Button onClick={saveResale}>Save</Button>
          </div>
        </div>
      )}

      {tab === "loyalty" && (
        <div className={s.section}>
          <div className={s.rowStacked}>
            <div className={s.rowLabel}>
              <span className={s.rowName}>Enable loyalty program</span>
              <span className={s.rowHint}>
                Reward repeat customers with member tiers and earned wallet credit.
                Everything below is yours to tune — no fixed values.
              </span>
            </div>
            <label className={s.hoursToggle}>
              <input
                type="checkbox"
                checked={loyalty.enabled}
                onChange={(e) => setLoyaltyField("enabled", e.target.checked)}
              />
              <span>Enable loyalty</span>
            </label>
          </div>

          <div className={`${s.row2} ${s.row2Compact}`}>
            <label className={s.col}>
              <span className={s.rowName}>Earn rate (%)</span>
              <input
                aria-label="earn rate percent" type="number" min={0} max={100} step={0.5}
                value={Math.round(loyalty.earn_rate * 1000) / 10}
                onChange={(e) => setLoyaltyField("earn_rate", Number(e.target.value) / 100)}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>% of food subtotal credited to the customer's wallet on delivery.</span>
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Max credit per order (AED)</span>
              <input
                aria-label="earn max per order" type="number" min={0}
                value={loyalty.earn_max_per_order_aed}
                onChange={(e) => setLoyaltyField("earn_max_per_order_aed", Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Credit expires (days)</span>
              <input
                aria-label="credit ttl days" type="number" min={0}
                value={loyalty.credit_ttl_days}
                onChange={(e) => setLoyaltyField("credit_ttl_days", Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>0 = never expires.</span>
            </label>
          </div>

          {LOYALTY_TIERS.map((tier) => (
            <div key={tier} className={s.rowStacked}>
              <div className={s.rowLabel}>
                <span className={s.rowName}>{TIER_LABELS[tier]}</span>
              </div>
              <div className={`${s.row2} ${s.row2Compact}`}>
                <label className={s.col}>
                  <span className={s.rowName}>Min orders</span>
                  <input aria-label={`${tier} min orders`} type="number" min={0}
                    value={loyalty.tiers[tier].min_orders}
                    onChange={(e) => setTierField(tier, "min_orders", Number(e.target.value))}
                    onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`} />
                </label>
                <label className={s.col}>
                  <span className={s.rowName}>Min spend (AED)</span>
                  <input aria-label={`${tier} min spend`} type="number" min={0}
                    value={loyalty.tiers[tier].min_spend_aed}
                    onChange={(e) => setTierField(tier, "min_spend_aed", Number(e.target.value))}
                    onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`} />
                </label>
                <label className={s.col}>
                  <span className={s.rowName}>Max recency (days)</span>
                  <input aria-label={`${tier} max recency`} type="number" min={0}
                    value={loyalty.tiers[tier].max_recency_days}
                    onChange={(e) => setTierField(tier, "max_recency_days", Number(e.target.value))}
                    onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`} />
                </label>
                <label className={s.col}>
                  <span className={s.rowName}>Reward AED</span>
                  <input aria-label={`${tier} reward aed`} type="number" min={0}
                    value={loyalty.tier_rewards[tier]?.discount_aed ?? 0}
                    onChange={(e) => setRewardField(tier, "discount_aed", Number(e.target.value))}
                    onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`} />
                </label>
                <label className={s.col}>
                  <span className={s.rowName}>Reward every N orders</span>
                  <input aria-label={`${tier} reward every n`} type="number" min={0}
                    value={loyalty.tier_rewards[tier]?.every_n_orders ?? 0}
                    onChange={(e) => setRewardField(tier, "every_n_orders", Number(e.target.value))}
                    onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`} />
                </label>
              </div>
            </div>
          ))}

          <div className={`${s.row2} ${s.row2Compact}`}>
            <label className={s.col}>
              <span className={s.rowName}>Demotion grace (days)</span>
              <input aria-label="demotion grace days" type="number" min={0}
                value={loyalty.demotion_grace_days}
                onChange={(e) => setLoyaltyField("demotion_grace_days", Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`} />
              <span className={s.rowHint}>Quiet days allowed before a tier is lost.</span>
            </label>
          </div>
          <div className={s.rowStacked}>
            <div className={s.rowLabel}>
              <span className={s.rowName}>Apply to catalog orders</span>
            </div>
            <label className={s.hoursToggle}>
              <input type="checkbox" checked={loyalty.scope_includes_catalog}
                onChange={(e) => setLoyaltyField("scope_includes_catalog", e.target.checked)} />
              <span>Include catalog orders</span>
            </label>
          </div>

          <div className={s.actions}>
            <Button onClick={saveLoyalty}>Save</Button>
          </div>
        </div>
      )}

      {tab === "cart" && (
        <div className={s.section}>
          <div className={s.rowStacked}>
            <div className={s.rowLabel}>
              <span className={s.rowName}>Cart reminder</span>
              <span className={s.rowHint}>
                Send one WhatsApp nudge ("you still have items in your cart") to customers
                who add items but don't check out. Turn off if you'd rather not message them.
              </span>
            </div>
            <label className={s.hoursToggle}>
              <input
                type="checkbox"
                checked={cartReminder}
                onChange={(e) => setCartReminder(e.target.checked)}
              />
              <span>Send cart reminder</span>
            </label>
          </div>
          <div className={`${s.row2} ${s.row2Compact}`}>
            <label className={s.col}>
              <span className={s.rowName}>Remind after (minutes)</span>
              <input
                aria-label="remind after minutes" type="number" min={1} max={1440}
                value={cartRecoveryMin} onChange={(e) => setCartRecoveryMin(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
                disabled={!cartReminder}
              />
              <span className={s.rowHint}>How long a cart can sit quiet before the reminder is sent.</span>
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Clear cart after (minutes)</span>
              <input
                aria-label="clear cart after minutes" type="number" min={1} max={1440}
                value={cartExpiryMin} onChange={(e) => setCartExpiryMin(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>
                After this much quiet time an abandoned cart is emptied automatically.
                A customer who returns before then is asked to continue it or start fresh.
              </span>
            </label>
          </div>
          <div className={s.actions}>
            <Button onClick={saveCart}>Save</Button>
          </div>
        </div>
      )}

      {tab === "dispatch" && (
        <div className={s.section}>
          <div className={s.rowStacked}>
            <div className={s.rowLabel}>
              <span className={s.rowName}>Quick presets</span>
              <span className={s.rowHint}>
                One-click starting points for routing and batching. Adjust fields below, then Save.
              </span>
            </div>
            <div className={s.presets} role="group" aria-label="Dispatch presets">
              {DISPATCH_PRESET_BUTTONS.map((p) => (
                <button
                  key={p.key}
                  type="button"
                  className={s.chip}
                  title={p.hint}
                  onClick={() => applyDispatchPreset(p.key)}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <label className={`${s.col} ${s.colField}`}>
            <span className={s.rowName}>Dispatch engine</span>
            <select
              aria-label="dispatch engine"
              value={dispatchEngine}
              onChange={(e) => setDispatchEngine(e.target.value as "greedy" | "ortools")}
              className={s.input}
            >
              <option value="greedy">Greedy — proximity batching (rollback)</option>
              <option value="ortools">OR-Tools — SLA-first route optimizer (default)</option>
            </select>
            <span className={s.rowHint}>
              OR Tools optimizes routes and assignment jointly and drops orders that can't
              make the 40 min SLA (with a manager alert). Pilot per restaurant.
            </span>
          </label>
          <h4 className={s.groupTitle}>Batching</h4>
          <div className={`${s.row2} ${s.row2Compact}`}>
            <label className={s.col}>
              <span className={s.rowName}>Group orders within (km)</span>
              <input
                aria-label="batch proximity km" type="number" min={0.1} max={10} step={0.1}
                value={batchProximity} onChange={(e) => setBatchProximity(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>Two orders this close together can share one rider trip.</span>
            </label>
            <label className={s.col}>
              <span className={s.rowName}>Wait to group (sec)</span>
              <input
                aria-label="batch hold seconds" type="number" min={0} max={600} step={10}
                value={holdSeconds} onChange={(e) => setHoldSeconds(Number(e.target.value))}
                onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>Hold a ready order this long so a nearby one can join its trip. 0 = send each order right away.</span>
            </label>
          </div>
          <label className={`${s.col} ${s.colField}`}>
            <span className={s.rowName}>On the way detour (km), 0 = off</span>
            <input
              aria-label="batch max detour km" type="number" min={0} max={10} step={0.1}
              value={maxDetour} onChange={(e) => setMaxDetour(Number(e.target.value))}
              onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
            />
            <span className={s.rowHint}>
              Let a rider drop an order that's at most this far off the route to a farther
              one. 0 keeps simple nearby grouping. The 40 min SLA is always enforced.
            </span>
          </label>
          <label className={`${s.col} ${s.colField}`}>
            <span className={s.rowName}>SLA buffer per extra stop (min)</span>
            <input
              aria-label="sla buffer per order minutes" type="number" min={0} max={30} step={1}
              value={slaBuffer} onChange={(e) => setSlaBuffer(Number(e.target.value))}
              onFocus={(e) => e.target.select()} className={`${s.input} ${s.inputNum}`}
            />
            <span className={s.rowHint}>
              Minutes added to the internal SLA budget for each extra batched stop. 10 min per
              stop keeps the 40 min customer promise with headroom.
            </span>
          </label>

          <h4 className={s.groupTitle}>Delivery zones</h4>
          <p className={s.rowHint}>
            Named areas for same-zone batching. Orders in the same zone can batch even when farther apart.
          </p>
          {deliveryZones.map((zone, idx) => (
            <div key={idx} className={`${s.row2} ${s.row2Compact}`}>
              <label className={s.col}>
                <span className={s.rowName}>Name</span>
                <input
                  aria-label={`zone ${idx + 1} name`}
                  className={s.input}
                  value={zone.name}
                  onChange={(e) => updateDeliveryZone(idx, { name: e.target.value })}
                />
              </label>
              <label className={s.col}>
                <span className={s.rowName}>Center lat</span>
                <input
                  aria-label={`zone ${idx + 1} center lat`}
                  type="number"
                  step="0.0001"
                  className={`${s.input} ${s.inputNum}`}
                  value={zone.center_lat}
                  onChange={(e) => updateDeliveryZone(idx, { center_lat: Number(e.target.value) })}
                />
              </label>
              <label className={s.col}>
                <span className={s.rowName}>Center lng</span>
                <input
                  aria-label={`zone ${idx + 1} center lng`}
                  type="number"
                  step="0.0001"
                  className={`${s.input} ${s.inputNum}`}
                  value={zone.center_lng}
                  onChange={(e) => updateDeliveryZone(idx, { center_lng: Number(e.target.value) })}
                />
              </label>
              <label className={s.col}>
                <span className={s.rowName}>Radius (km)</span>
                <input
                  aria-label={`zone ${idx + 1} radius km`}
                  type="number"
                  min={0.1}
                  max={10}
                  step={0.1}
                  className={`${s.input} ${s.inputNum}`}
                  value={zone.radius_km}
                  onChange={(e) => updateDeliveryZone(idx, { radius_km: Number(e.target.value) })}
                />
              </label>
              <button type="button" className={s.chip} onClick={() => removeDeliveryZone(idx)}>
                Remove
              </button>
            </div>
          ))}
          <button type="button" className={s.addTier} onClick={addDeliveryZone}>
            Add delivery zone
          </button>

          <h4 className={s.groupTitle}>Kitchen</h4>
          <div className={`${s.row2} ${s.row2Compact}`}>
            <label className={s.col}>
              <span className={s.rowName}>Prep dispatch lead (min)</span>
              <input
                aria-label="prep dispatch lead minutes"
                type="number"
                min={1}
                max={30}
                value={prepLeadMin}
                onChange={(e) => setPrepLeadMin(Number(e.target.value))}
                onFocus={(e) => e.target.select()}
                className={`${s.input} ${s.inputNum}`}
              />
              <span className={s.rowHint}>
                How many minutes before prep_deadline a preparing order enters the dispatch pool.
              </span>
            </label>
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
              <span className={s.rowName}>Expedite radius (km)</span>
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

          {tab === "integrations" && <ApiKeysSection />}
          {tab === "payments" && <PaymentsSection />}
          </>
          )}
        </div>
      </div>

      {showDisconnect && (
        <ConfirmDialog
          title="Disconnect WhatsApp?"
          message="This clears your stored WhatsApp (Meta) connection and sends you to onboarding to reconnect. Your menu, orders and settings stay — but the bot won't reply on WhatsApp until you reconnect."
          confirmLabel="Disconnect"
          danger
          busy={disconnecting}
          onConfirm={onDisconnectWhatsApp}
          onCancel={() => !disconnecting && setShowDisconnect(false)}
        />
      )}
    </div>
  );
}

// Skeleton shown while GET /me loads — mirrors a settings form: a couple of
// labelled fields and a save action, so the panel keeps its shape.
function SettingsSkeleton() {
  return (
    <div className={s.section} aria-busy="true" aria-label="Loading settings">
      <div className={s.row2}>
        {[0, 1].map((i) => (
          <div key={i} className={s.col}>
            <span className={`${s.sk} ${s.skLabel}`} />
            <span className={`${s.sk} ${s.skInput}`} />
            <span className={`${s.sk} ${s.skHint}`} />
          </div>
        ))}
      </div>
      <div className={s.colField}>
        <span className={`${s.sk} ${s.skLabel}`} />
        <span className={`${s.sk} ${s.skInput}`} style={{ maxWidth: 320 }} />
        <span className={`${s.sk} ${s.skHint}`} />
      </div>
      <div className={s.actions}>
        <span className={`${s.sk} ${s.skBtn}`} />
      </div>
    </div>
  );
}

// Partner API keys: generate (shown once), list, and revoke. The full secret is
// returned by the backend only at creation, so we surface it in a one-time
// reveal box with a copy button and never store/show it again.
function ApiKeysSection() {
  const [keys, setKeys] = useState<ApiKey[] | null>(null);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [revealed, setRevealed] = useState<string | null>(null);
  const [pendingRevoke, setPendingRevoke] = useState<ApiKey | null>(null);
  const [revoking, setRevoking] = useState(false);

  function reload() {
    listApiKeys().then(setKeys).catch(() => setKeys([]));
  }
  useEffect(() => { reload(); }, []);

  async function onCreate() {
    const name = label.trim();
    if (!name) {
      toast("Give the key a name first.", "error");
      return;
    }
    setCreating(true);
    try {
      const created = await createApiKey(name);
      setRevealed(created.api_key);
      setLabel("");
      reload();
      toast("Key created. Copy it now, it won't be shown again.", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not create the key.", "error");
    } finally {
      setCreating(false);
    }
  }

  async function onRevoke() {
    if (!pendingRevoke) return;
    setRevoking(true);
    try {
      await revokeApiKey(pendingRevoke.id);
      reload();
      toast("Key revoked.");
      setPendingRevoke(null);
    } catch {
      toast("Could not revoke the key.", "error");
    } finally {
      setRevoking(false);
    }
  }

  function copy(text: string) {
    navigator.clipboard?.writeText(text).then(
      () => toast("Copied to clipboard."),
      () => {},
    );
  }

  return (
    <div className={s.section}>
      <div className={s.apiCreateRow}>
        <input
          className={s.input}
          placeholder="Key name (e.g. Acme POS)"
          value={label}
          maxLength={120}
          onChange={(e) => setLabel(e.target.value)}
        />
        <Button onClick={onCreate} disabled={creating}>
          {creating ? "Generating…" : "Generate key"}
        </Button>
      </div>

      {revealed && (
        <div className={s.apiReveal} role="alert">
          <div className={s.apiRevealHead}>
            <span>🔑 Copy this key now, it won't be shown again.</span>
            <button type="button" className={s.apiCopyBtn} onClick={() => copy(revealed)}>
              Copy
            </button>
          </div>
          <code className={s.apiKeyValue}>{revealed}</code>
          <button type="button" className={s.apiDismiss} onClick={() => setRevealed(null)}>
            Done
          </button>
        </div>
      )}

      <p className={s.rowHint}>
        Partners send the header <code>X-API-Key: &lt;key&gt;</code> to pull read-only data
        from <code>/api/v1/partner/customers</code>, scoped to your restaurant only.
      </p>

      {keys === null ? (
        <table className={s.apiTable} aria-busy="true" aria-label="Loading API keys">
          <thead>
            <tr>
              <th>Name</th><th>Key</th><th>Last used</th><th>Status</th><th aria-label="actions" />
            </tr>
          </thead>
          <tbody>
            {[0, 1, 2].map((i) => (
              <tr key={i}>
                <td><span className={`${s.sk} ${s.skCell}`} style={{ width: 120 }} /></td>
                <td><span className={`${s.sk} ${s.skCell}`} style={{ width: 100 }} /></td>
                <td><span className={`${s.sk} ${s.skCell}`} style={{ width: 140 }} /></td>
                <td><span className={`${s.sk} ${s.skCell}`} style={{ width: 56 }} /></td>
                <td><span className={`${s.sk} ${s.skCell}`} style={{ width: 56 }} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : keys.length === 0 ? (
        <p className={s.rowHint}>No API keys yet. Generate one above to share with your partner.</p>
      ) : (
        <table className={s.apiTable}>
          <thead>
            <tr>
              <th>Name</th><th>Key</th><th>Last used</th><th>Status</th><th aria-label="actions" />
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id} className={k.revoked_at ? s.apiRowRevoked : ""}>
                <td>{k.label}</td>
                <td><code>{k.key_prefix}…</code></td>
                <td>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "—"}</td>
                <td>
                  {k.revoked_at
                    ? <span className={s.apiBadgeRevoked}>Revoked</span>
                    : <span className={s.apiBadgeActive}>Active</span>}
                </td>
                <td>
                  {!k.revoked_at && (
                    <button type="button" className={s.apiRevokeBtn} onClick={() => setPendingRevoke(k)}>
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {pendingRevoke && (
        <ConfirmDialog
          title="Revoke API key?"
          message={`Revoke "${pendingRevoke.label}" (${pendingRevoke.key_prefix}…)? The partner using it loses access immediately.`}
          confirmLabel="Revoke key"
          danger
          busy={revoking}
          onConfirm={onRevoke}
          onCancel={() => !revoking && setPendingRevoke(null)}
        />
      )}
    </div>
  );
}

function PaymentsSection() {
  const [status, setStatus] = useState<CredentialsStatus | null>(null);
  const [secretKey, setSecretKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  function reload() {
    getPaymentCredentials().then(setStatus).catch(() => setStatus({ provider: "mock", configured: false }));
  }
  useEffect(() => { reload(); }, []);

  async function onSave() {
    const key = secretKey.trim();
    if (!key) {
      toast("Paste your Stripe secret key first.", "error");
      return;
    }
    setSaving(true);
    try {
      await setPaymentCredentials("stripe", key);
      setSecretKey("");
      reload();
      toast("Stripe connected. Card payments now run against your account.", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save credentials.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    setDeleting(true);
    try {
      await deletePaymentCredentials();
      reload();
      toast("Stripe disconnected. Card payments will run in test/mock mode.");
      setPendingDelete(false);
    } catch {
      toast("Could not disconnect.", "error");
    } finally {
      setDeleting(false);
    }
  }

  if (status === null) {
    return <div className={s.section} aria-busy="true">Loading…</div>;
  }

  return (
    <div className={s.section}>
      <p className={s.rowHint}>
        Status: {status.configured
          ? <strong>Stripe connected</strong>
          : <strong>Not connected — card charges run in mock/test mode</strong>}
      </p>

      <div className={s.apiCreateRow}>
        <input
          className={s.input}
          type="password"
          placeholder="sk_live_… or sk_test_…"
          value={secretKey}
          onChange={(e) => setSecretKey(e.target.value)}
        />
        <Button onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : status.configured ? "Update key" : "Connect Stripe"}
        </Button>
      </div>

      {status.configured && (
        <Button variant="ghost" onClick={() => setPendingDelete(true)}>
          Disconnect
        </Button>
      )}

      {pendingDelete && (
        <ConfirmDialog
          title="Disconnect Stripe?"
          message="Card payments will fall back to mock/test mode until you connect a new key."
          confirmLabel="Disconnect"
          danger
          busy={deleting}
          onConfirm={onDelete}
          onCancel={() => !deleting && setPendingDelete(false)}
        />
      )}
    </div>
  );
}
