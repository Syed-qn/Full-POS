/**
 * Rush-hour load fixtures for UI unit / performance tests.
 * Deterministic generators — no network, no random() without a seed.
 *
 * Prefer unit tests only. Do not wire into production screens without
 * gating behind import.meta.env.DEV.
 */
import type { KdsStation } from "../../lib/kdsApi";
import type { OrderOut, OrderStatus, OrganizationBranchOut, RiderOut, RiderStatus } from "../../lib/types";
import { remainingMs, SLA_WINDOW_MS } from "../../lib/sla";

// ── Constants ────────────────────────────────────────────────────────────────

/** Fixed reference "now" so SLA math is stable across test runs. */
export const RUSH_HOUR_NOW = Date.parse("2026-07-09T19:30:00Z");

export const RUSH_HOUR_ORDER_COUNT = 100;
export const RUSH_HOUR_RIDER_COUNT = 20;
export const RUSH_HOUR_CHANNEL_COUNT = 8;
export const RUSH_HOUR_STATION_COUNT = 6;
export const RUSH_HOUR_BRANCH_COUNT = 5;

/** Live board statuses (excludes terminal/resale states for the active feed). */
const LIVE_STATUSES: OrderStatus[] = [
  "confirmed",
  "preparing",
  "ready",
  "assigned",
  "picked_up",
  "arriving",
];

const RIDER_STATUSES: RiderStatus[] = [
  "available",
  "on_delivery",
  "on_delivery",
  "available",
  "off_shift",
];

const DISH_POOL = [
  { dish_number: 110, name: "Chicken Biryani", price_aed: "22.00" },
  { dish_number: 201, name: "Mutton Karahi", price_aed: "35.00" },
  { dish_number: 305, name: "Beef Nihari", price_aed: "28.00" },
  { dish_number: 112, name: "Chicken Mandi", price_aed: "26.00" },
  { dish_number: 401, name: "Shawarma Plate", price_aed: "18.00" },
  { dish_number: 502, name: "Fries Large", price_aed: "12.00" },
  { dish_number: 601, name: "Mango Lassi", price_aed: "10.00" },
  { dish_number: 703, name: "Mixed Grill", price_aed: "55.00" },
] as const;

const CUSTOMER_FIRST = [
  "Ali", "Omar", "Sara", "Fatima", "Hassan", "Noor", "Yousef", "Layla",
  "Ahmed", "Mariam", "Khalid", "Aisha", "Zain", "Huda", "Rami", "Dina",
];
const CUSTOMER_LAST = [
  "Hassan", "Farouq", "Khan", "Al Mazrouei", "Rahman", "Singh", "Al Suwaidi",
  "Patel", "Ibrahim", "Nasser", "Abbas", "Malik", "Saleh", "Qureshi",
];

const AREA_POOL = [
  { address: "Jumeirah 1, Villa 12", lat: 25.2048, lng: 55.2708 },
  { address: "Business Bay, Tower 3", lat: 25.1865, lng: 55.2654 },
  { address: "Al Barsha 2", lat: 25.1119, lng: 55.2003 },
  { address: "Marina Walk, Apt 1804", lat: 25.0805, lng: 55.1403 },
  { address: "Downtown, Boulevard Point", lat: 25.1972, lng: 55.2744 },
  { address: "Deira, Al Rigga Rd", lat: 25.2650, lng: 55.3220 },
  { address: "JLT Cluster W, Tower 1", lat: 25.0693, lng: 55.1415 },
  { address: "Palm Jumeirah, Shoreline 8", lat: 25.1124, lng: 55.1390 },
] as const;

/**
 * Channel labels for filters / KPI chips (WhatsApp + aggregators + walk-in).
 * Exactly 8 — matches RUSH_HOUR_CHANNEL_COUNT.
 */
export const CHANNEL_LABELS = [
  "WhatsApp",
  "Talabat",
  "Deliveroo",
  "Careem",
  "Noon Food",
  "Website",
  "Walk-in",
  "Phone",
] as const;

export type ChannelLabel = (typeof CHANNEL_LABELS)[number];

const STATION_DEFS: Array<{ name: string; station_type: string; kitchen_code: string }> = [
  { name: "Grill", station_type: "grill", kitchen_code: "main" },
  { name: "Tandoor", station_type: "tandoor", kitchen_code: "main" },
  { name: "Fry", station_type: "fry", kitchen_code: "main" },
  { name: "Cold / Salad", station_type: "cold", kitchen_code: "main" },
  { name: "Drinks", station_type: "drinks", kitchen_code: "main" },
  { name: "Expo / Pass", station_type: "expo", kitchen_code: "main" },
];

const BRANCH_DEFS: Array<{ name: string; region: string; lat: number; lng: number }> = [
  { name: "Jumeirah", region: "Dubai", lat: 25.2048, lng: 55.2708 },
  { name: "Business Bay", region: "Dubai", lat: 25.1865, lng: 55.2654 },
  { name: "Marina", region: "Dubai", lat: 25.0805, lng: 55.1403 },
  { name: "Deira", region: "Dubai", lat: 25.2650, lng: 55.3220 },
  { name: "Abu Dhabi Corniche", region: "Abu Dhabi", lat: 24.4667, lng: 54.3667 },
];

// ── Deterministic helpers ────────────────────────────────────────────────────

/** Mulberry32 PRNG — same seed → same sequence across runs. */
export function createSeededRng(seed: number): () => number {
  let t = seed >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(rng: () => number, arr: readonly T[]): T {
  return arr[Math.floor(rng() * arr.length)]!;
}

function money(n: number): string {
  return n.toFixed(2);
}

/**
 * LiveOps treats remaining ≤ 10 min as late (see LiveOpsScreen.isLate).
 * Breach is remaining ≤ 0.
 */
export function isLateOrder(order: OrderOut, now: number = RUSH_HOUR_NOW): boolean {
  return remainingMs(order.sla_started_at, now) <= 10 * 60_000;
}

export function isBreachedOrder(order: OrderOut, now: number = RUSH_HOUR_NOW): boolean {
  return remainingMs(order.sla_started_at, now) <= 0;
}

export function filterLateOrders(orders: OrderOut[], now: number = RUSH_HOUR_NOW): OrderOut[] {
  return orders.filter((o) => isLateOrder(o, now));
}

export function filterActiveLiveOrders(orders: OrderOut[]): OrderOut[] {
  const active = new Set<OrderStatus>(LIVE_STATUSES);
  return orders.filter((o) => active.has(o.status));
}

// ── Generators ───────────────────────────────────────────────────────────────

export type RushHourOrderOpts = {
  count?: number;
  /** Epoch ms used as "now" for SLA offsets. Default RUSH_HOUR_NOW. */
  now?: number;
  /** PRNG seed. Default 20260709. */
  seed?: number;
  /**
   * Fraction of orders that are late (≤10 min remaining) or already breached.
   * Default 0.18 (~18 of 100).
   */
  lateFraction?: number;
};

/**
 * Generate mock live orders with mixed FSM statuses and intentional late SLAs.
 * IDs start at 10_001 so they never collide with small static fixtures (47–49).
 */
export function generateRushHourOrders(opts: RushHourOrderOpts = {}): OrderOut[] {
  const count = opts.count ?? RUSH_HOUR_ORDER_COUNT;
  const now = opts.now ?? RUSH_HOUR_NOW;
  const seed = opts.seed ?? 20260709;
  const lateFraction = opts.lateFraction ?? 0.18;
  const rng = createSeededRng(seed);
  const lateTarget = Math.max(1, Math.round(count * lateFraction));

  const orders: OrderOut[] = [];
  for (let i = 0; i < count; i++) {
    const id = 10_001 + i;
    const status = LIVE_STATUSES[i % LIVE_STATUSES.length]!;
    const isLateSlot = i < lateTarget;

    // Late: 30–50 min elapsed (≤10 min remaining or breached).
    // Healthy: 2–25 min elapsed (comfortable buffer).
    const elapsedMin = isLateSlot
      ? 30 + Math.floor(rng() * 20)
      : 2 + Math.floor(rng() * 23);
    const slaStarted = new Date(now - elapsedMin * 60_000).toISOString();
    const created = new Date(Date.parse(slaStarted) - 30_000 - Math.floor(rng() * 90_000)).toISOString();

    const dish = pick(rng, DISH_POOL);
    const qty = 1 + Math.floor(rng() * 3);
    const unit = Number(dish.price_aed);
    const itemTotal = unit * qty;
    // Delivery fee tiers (spec): ≤3 free / 3–5 AED5 / >5 AED10 — mock mix
    const fee = pick(rng, [0, 0, 5, 10]);
    const total = itemTotal + fee;

    const first = pick(rng, CUSTOMER_FIRST);
    const last = pick(rng, CUSTOMER_LAST);
    const area = pick(rng, AREA_POOL);
    const channel = CHANNEL_LABELS[i % CHANNEL_LABELS.length]!;

    const needsRider =
      status === "assigned" || status === "picked_up" || status === "arriving";
    const riderIdx = needsRider ? (i % RUSH_HOUR_RIDER_COUNT) + 1 : null;

    const cookEst = 12 + Math.floor(rng() * 10);
    const prepDeadline = new Date(
      Date.parse(slaStarted) + cookEst * 60_000,
    ).toISOString();

    orders.push({
      id,
      order_number: `RH-${String(id).slice(-4)}`,
      status,
      customer_name: `${first} ${last}`,
      customer_phone: `+9715${String(10000000 + (i * 137) % 90000000).padStart(8, "0")}`,
      items: [
        {
          dish_number: dish.dish_number,
          name: dish.name,
          qty,
          price_aed: dish.price_aed,
        },
      ],
      total_aed: money(total),
      rider_id: riderIdx,
      rider_name: riderIdx != null ? `Rider ${riderIdx}` : null,
      sla_started_at: slaStarted,
      prep_deadline: prepDeadline,
      cook_estimate_minutes: cookEst,
      created_at: created,
      address: area.address,
      lat: area.lat + (rng() - 0.5) * 0.01,
      lng: area.lng + (rng() - 0.5) * 0.01,
      order_type: channel === "Walk-in" ? "dine_in" : "delivery",
      priority: isLateSlot && rng() > 0.5 ? "high" : "normal",
      source_channel: channel.toLowerCase().replace(/\s+/g, "_"),
      aggregator_source:
        channel === "WhatsApp" || channel === "Website" || channel === "Walk-in" || channel === "Phone"
          ? null
          : channel.toLowerCase().replace(/\s+/g, "_"),
      batch_id: i % 11 === 0 ? 9000 + Math.floor(i / 11) : null,
      batch_size: i % 11 === 0 ? 2 : null,
      batch_order_numbers: i % 11 === 0 ? [`RH-${String(id).slice(-4)}`, `RH-${String(id + 1).slice(-4)}`] : undefined,
      batch_preview: status === "confirmed" && i % 7 === 0 ? String.fromCharCode(65 + (i % 5)) : null,
    });
  }

  return orders;
}

export type RushHourRiderOpts = {
  count?: number;
  now?: number;
  seed?: number;
};

/** Generate mock fleet riders for load tests. IDs 1..count. */
export function generateRushHourRiders(opts: RushHourRiderOpts = {}): RiderOut[] {
  const count = opts.count ?? RUSH_HOUR_RIDER_COUNT;
  const now = opts.now ?? RUSH_HOUR_NOW;
  const rng = createSeededRng(opts.seed ?? 4242);

  const riders: RiderOut[] = [];
  for (let i = 0; i < count; i++) {
    const id = i + 1;
    const status = RIDER_STATUSES[i % RIDER_STATUSES.length]!;
    const onDuty = status !== "off_shift" && status !== "deactivated";
    const hasLoc = status !== "off_shift";
    const base = AREA_POOL[i % AREA_POOL.length]!;

    riders.push({
      id,
      name: `Rider ${id}`,
      phone: `+9715${String(20000000 + id * 1111).padStart(8, "0")}`,
      status,
      on_duty: onDuty,
      delivered_24h: Math.floor(rng() * 18),
      delivered_lifetime: 50 + Math.floor(rng() * 400),
      last_lat: hasLoc ? base.lat + (rng() - 0.5) * 0.02 : null,
      last_lng: hasLoc ? base.lng + (rng() - 0.5) * 0.02 : null,
      last_location_at: hasLoc
        ? new Date(now - Math.floor(rng() * 5 * 60_000)).toISOString()
        : null,
    });
  }
  return riders;
}

/** 8 channel display labels (stable export). */
export function generateChannelLabels(): ChannelLabel[] {
  return [...CHANNEL_LABELS];
}

/** 6 KDS stations covering grill → expo. */
export function generateKdsStations(): KdsStation[] {
  return STATION_DEFS.slice(0, RUSH_HOUR_STATION_COUNT).map((def, i) => ({
    id: i + 1,
    name: def.name,
    station_type: def.station_type,
    kitchen_code: def.kitchen_code,
    printer_ip: i < 4 ? `192.168.1.${50 + i}` : null,
    printer_port: i < 4 ? 9100 : null,
    fallback_station_id: i === 5 ? 1 : null,
    is_active: true,
  }));
}

/** 5 multi-branch org rows. */
export function generateBranches(): OrganizationBranchOut[] {
  return BRANCH_DEFS.slice(0, RUSH_HOUR_BRANCH_COUNT).map((def, i) => ({
    id: i + 1,
    name: def.name,
    region: def.region,
    currency: "AED",
    locale: "en-AE",
    is_central_kitchen: i === 0,
    lat: def.lat,
    lng: def.lng,
  }));
}

export type RushHourDataset = {
  now: number;
  orders: OrderOut[];
  riders: RiderOut[];
  channels: ChannelLabel[];
  stations: KdsStation[];
  branches: OrganizationBranchOut[];
  lateOrders: OrderOut[];
};

/** Full rush-hour bundle used by load / board unit tests. */
export function buildRushHourDataset(opts: RushHourOrderOpts = {}): RushHourDataset {
  const now = opts.now ?? RUSH_HOUR_NOW;
  const orders = generateRushHourOrders({ ...opts, now });
  return {
    now,
    orders,
    riders: generateRushHourRiders({ now, seed: opts.seed }),
    channels: generateChannelLabels(),
    stations: generateKdsStations(),
    branches: generateBranches(),
    lateOrders: filterLateOrders(orders, now),
  };
}

/** SLA helpers re-exported for fixture consumers / tests. */
export { remainingMs, SLA_WINDOW_MS };
