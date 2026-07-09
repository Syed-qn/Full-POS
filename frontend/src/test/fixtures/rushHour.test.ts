import { describe, expect, it } from "vitest";
import {
  RUSH_HOUR_BRANCH_COUNT,
  RUSH_HOUR_CHANNEL_COUNT,
  RUSH_HOUR_NOW,
  RUSH_HOUR_ORDER_COUNT,
  RUSH_HOUR_RIDER_COUNT,
  RUSH_HOUR_STATION_COUNT,
  buildRushHourDataset,
  createSeededRng,
  filterLateOrders,
  generateBranches,
  generateChannelLabels,
  generateKdsStations,
  generateRushHourOrders,
  generateRushHourRiders,
  isBreachedOrder,
  isLateOrder,
  remainingMs,
} from "./rushHour";
import { remainingMs as slaRemainingMs } from "../../lib/sla";

describe("rushHour fixtures", () => {
  it("generates exactly 100 live orders with mixed statuses", () => {
    const orders = generateRushHourOrders();
    expect(orders).toHaveLength(RUSH_HOUR_ORDER_COUNT);
    expect(orders).toHaveLength(100);

    const statuses = new Set(orders.map((o) => o.status));
    expect(statuses.has("confirmed")).toBe(true);
    expect(statuses.has("preparing")).toBe(true);
    expect(statuses.has("ready")).toBe(true);
    expect(statuses.has("assigned")).toBe(true);
    expect(statuses.has("picked_up")).toBe(true);
    expect(statuses.has("arriving")).toBe(true);

    // Unique ids, starting above static fixture range
    const ids = orders.map((o) => o.id);
    expect(new Set(ids).size).toBe(100);
    expect(Math.min(...ids)).toBeGreaterThanOrEqual(10_001);
  });

  it("includes late SLA orders (≤10 min remaining at RUSH_HOUR_NOW)", () => {
    const orders = generateRushHourOrders();
    const late = filterLateOrders(orders, RUSH_HOUR_NOW);
    expect(late.length).toBeGreaterThan(0);
    // Default lateFraction 0.18 → ~18 late slots
    expect(late.length).toBeGreaterThanOrEqual(10);

    for (const o of late) {
      expect(isLateOrder(o, RUSH_HOUR_NOW)).toBe(true);
      expect(slaRemainingMs(o.sla_started_at, RUSH_HOUR_NOW)).toBeLessThanOrEqual(10 * 60_000);
    }

    // At least one fully breached (elapsed can hit 50 min in late bucket)
    const anyBreach = orders.some((o) => isBreachedOrder(o, RUSH_HOUR_NOW));
    expect(anyBreach).toBe(true);
  });

  it("generates 20 riders with mixed duty statuses", () => {
    const riders = generateRushHourRiders();
    expect(riders).toHaveLength(RUSH_HOUR_RIDER_COUNT);
    expect(riders).toHaveLength(20);

    const statuses = new Set(riders.map((r) => r.status));
    expect(statuses.has("available")).toBe(true);
    expect(statuses.has("on_delivery")).toBe(true);
    expect(statuses.has("off_shift")).toBe(true);

    expect(riders.every((r) => r.id >= 1 && r.id <= 20)).toBe(true);
    expect(riders.every((r) => r.phone.startsWith("+9715"))).toBe(true);
  });

  it("exports 8 channel labels", () => {
    const channels = generateChannelLabels();
    expect(channels).toHaveLength(RUSH_HOUR_CHANNEL_COUNT);
    expect(channels).toHaveLength(8);
    expect(channels).toContain("WhatsApp");
    expect(channels).toContain("Talabat");
    expect(channels).toContain("Deliveroo");
    expect(new Set(channels).size).toBe(8);
  });

  it("generates 6 KDS stations", () => {
    const stations = generateKdsStations();
    expect(stations).toHaveLength(RUSH_HOUR_STATION_COUNT);
    expect(stations).toHaveLength(6);
    expect(stations.map((s) => s.name)).toEqual(
      expect.arrayContaining(["Grill", "Tandoor", "Fry", "Expo / Pass"]),
    );
    expect(stations.every((s) => s.is_active)).toBe(true);
  });

  it("generates 5 branches", () => {
    const branches = generateBranches();
    expect(branches).toHaveLength(RUSH_HOUR_BRANCH_COUNT);
    expect(branches).toHaveLength(5);
    expect(branches[0]?.is_central_kitchen).toBe(true);
    expect(branches.every((b) => b.currency === "AED")).toBe(true);
  });

  it("buildRushHourDataset wires the full bundle", () => {
    const ds = buildRushHourDataset();
    expect(ds.now).toBe(RUSH_HOUR_NOW);
    expect(ds.orders).toHaveLength(100);
    expect(ds.riders).toHaveLength(20);
    expect(ds.channels).toHaveLength(8);
    expect(ds.stations).toHaveLength(6);
    expect(ds.branches).toHaveLength(5);
    expect(ds.lateOrders.length).toBeGreaterThan(0);
    expect(ds.lateOrders.length).toBe(filterLateOrders(ds.orders, ds.now).length);
  });

  it("is deterministic for the same seed", () => {
    const a = generateRushHourOrders({ seed: 99 });
    const b = generateRushHourOrders({ seed: 99 });
    expect(a).toEqual(b);

    const r1 = generateRushHourRiders({ seed: 7 });
    const r2 = generateRushHourRiders({ seed: 7 });
    expect(r1).toEqual(r2);
  });

  it("createSeededRng is stable", () => {
    const rng = createSeededRng(1);
    const first = [rng(), rng(), rng()];
    const rng2 = createSeededRng(1);
    expect([rng2(), rng2(), rng2()]).toEqual(first);
  });

  it("re-exports remainingMs consistent with sla module", () => {
    const orders = generateRushHourOrders({ count: 5 });
    for (const o of orders) {
      expect(remainingMs(o.sla_started_at, RUSH_HOUR_NOW)).toBe(
        slaRemainingMs(o.sla_started_at, RUSH_HOUR_NOW),
      );
    }
  });
});
