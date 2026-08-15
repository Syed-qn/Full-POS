import { useEffect, useState } from "react";
import { apiClient } from "./apiClient";

export type TaxConfig = {
  /** Fraction, e.g. 0.05. */
  rate: number;
  /** Percentage for display, e.g. 5. */
  percent: number;
  /** "inclusive" = the menu price already contains VAT. */
  mode: "inclusive" | "exclusive";
  /** False until the server has answered. Never print a rate while false. */
  ready: boolean;
};

/**
 * What the till holds before the server answers.
 *
 * The rate is 0, not 5. It used to default to the UAE standard, which meant a
 * restaurant on 20% saw "VAT (5% incl.)" for a beat and then watched it jump —
 * a wrong tax figure printed on a bill, however briefly, is worse than none.
 * `ready: false` tells the caller to show no percentage at all yet.
 */
export const PENDING_TAX_CONFIG: TaxConfig = {
  rate: 0,
  percent: 0,
  mode: "inclusive",
  ready: false,
};

/* Module-level cache so the second till screen of a shift paints its totals
   immediately instead of showing no rate for a moment. */
let cached: TaxConfig | null = null;
let inflight: Promise<TaxConfig> | null = null;

function normalise(raw: {
  vat_rate?: string;
  vat_percent?: number;
  pricing_mode?: string;
}): TaxConfig {
  const rate = Number(raw.vat_rate);
  const percent = Number(raw.vat_percent);
  return {
    rate: Number.isFinite(rate) ? rate : 0,
    percent: Number.isFinite(percent) ? percent : 0,
    mode: raw.pricing_mode === "exclusive" ? "exclusive" : "inclusive",
    ready: true,
  };
}

export async function fetchTaxConfig(): Promise<TaxConfig> {
  if (cached) return cached;
  if (!inflight) {
    inflight = apiClient
      .get<{ vat_rate: string; vat_percent: number; pricing_mode: string }>(
        "/api/v1/orders/tax-config",
      )
      .then((raw) => {
        cached = normalise(raw);
        return cached;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Drop the cache so a saved rate change is picked up without a reload. */
export function clearTaxConfigCache() {
  cached = null;
}

/**
 * VAT rate and pricing mode for the till, read from the restaurant's settings.
 *
 * Every till screen used to hardcode 5% and divide by a literal 1.05, so the
 * VAT rate on the Tax profile page moved the tax records while the customer's
 * printed bill went on saying 5%. One sale, two different VAT figures.
 */
export function useTaxConfig(): TaxConfig {
  const [cfg, setCfg] = useState<TaxConfig>(cached ?? PENDING_TAX_CONFIG);

  useEffect(() => {
    let cancelled = false;
    void fetchTaxConfig()
      .then((c) => {
        if (!cancelled) setCfg(c);
      })
      // A till that cannot reach the server still has to total a bill. Keep the
      // last known figures rather than blanking the VAT line.
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return cfg;
}

/**
 * Split a line total into net and VAT.
 *
 * inclusive: `amount` already contains VAT, so extract it.
 * exclusive: `amount` is net, so VAT is added on top and the gross is larger.
 */
export function splitVat(
  amount: number,
  cfg: TaxConfig,
): { net: number; vat: number; gross: number } {
  const rate = cfg.rate > 0 ? cfg.rate : 0;
  if (cfg.mode === "exclusive") {
    const vat = amount * rate;
    return { net: amount, vat, gross: amount + vat };
  }
  const net = amount / (1 + rate);
  return { net, vat: amount - net, gross: amount };
}

/**
 * The VAT contained in an amount that is actually being charged.
 *
 * Every till surface states tax this way, whatever the configured pricing mode,
 * because the amount charged is the one fact all of them share: nothing between
 * these screens and the customer adds VAT to it (`recompute_order_total` builds
 * subtotal + fee + charges − discounts and never adds `vat_amount_aed`). A screen
 * that printed an "on top" figure therefore showed a bill that did not add up —
 * 84.00 subtotal, 16.80 VAT, 84.00 total — and the arithmetic is the first thing
 * a guest checks.
 *
 * Pass the post-discount amount: tax is due on what was paid, not on the list price.
 */
export function vatIncludedIn(amount: number, cfg: TaxConfig): number {
  if (!(cfg.rate > 0) || !Number.isFinite(amount)) return 0;
  return amount - amount / (1 + cfg.rate);
}
