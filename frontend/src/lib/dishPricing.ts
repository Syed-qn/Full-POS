/**
 * What a dish actually costs — the number the till must SHOW, because it is the
 * number the server will CHARGE.
 *
 * This mirrors `effective_unit_price` in app/ordering/service.py exactly: a sale
 * price wins when it is greater than zero and below the base price. Anything else
 * (zero, negative, or above the base) is ignored rather than trusted, so a bad
 * sale price cannot quietly discount a dish to nothing.
 *
 * It exists because the two disagreed in production: a dish carrying
 * sale_price_aed 0.01 against a base of 20.00 rendered "20.00" on the till tile
 * and billed 0.02 for two. The cashier reads one number to the customer and the
 * bill says another — the kind of gap that is only ever found at the counter.
 */
export type PricedDish = {
  price_aed?: string | number | null;
  sale_price_aed?: string | number | null;
};

function toNumber(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** The unit price that will be billed. */
export function effectiveDishPrice(dish: PricedDish): number {
  const base = toNumber(dish.price_aed) ?? 0;
  const sale = toNumber(dish.sale_price_aed);
  if (sale !== null && sale > 0 && sale < base) return sale;
  return base;
}

/** True when a sale price is actually in force — drives the struck-through base. */
export function isOnSale(dish: PricedDish): boolean {
  const base = toNumber(dish.price_aed) ?? 0;
  const sale = toNumber(dish.sale_price_aed);
  return sale !== null && sale > 0 && sale < base;
}

/** Money as the till writes it everywhere else: two decimals, no currency word. */
export function money(n: number): string {
  return n.toFixed(2);
}
