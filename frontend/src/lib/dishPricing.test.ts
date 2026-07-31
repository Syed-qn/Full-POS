import { describe, expect, it } from "vitest";
import { effectiveDishPrice, isOnSale, money } from "./dishPricing";

describe("effectiveDishPrice", () => {
  it("bills the sale price when one is in force", () => {
    // The production case that started this: Chicken Biryani, base 20.00 with
    // sale_price_aed 0.01. The tile showed 20.00 and two of them billed 0.02.
    const dish = { price_aed: "20.00", sale_price_aed: "0.01" };
    expect(effectiveDishPrice(dish)).toBe(0.01);
    expect(isOnSale(dish)).toBe(true);
  });

  it("falls back to the base price when there is no sale", () => {
    for (const sale of [null, undefined, ""]) {
      const dish = { price_aed: "26.00", sale_price_aed: sale };
      expect(effectiveDishPrice(dish)).toBe(26);
      expect(isOnSale(dish)).toBe(false);
    }
  });

  it("ignores a sale price that is not below the base", () => {
    // Mirrors the server: a sale price at or above the base is not a sale, and
    // trusting it would let a bad edit RAISE the price at the till.
    expect(effectiveDishPrice({ price_aed: "20.00", sale_price_aed: "20.00" })).toBe(20);
    expect(effectiveDishPrice({ price_aed: "20.00", sale_price_aed: "25.00" })).toBe(20);
    expect(isOnSale({ price_aed: "20.00", sale_price_aed: "25.00" })).toBe(false);
  });

  it("ignores a zero or negative sale price", () => {
    // Zero is how the server reads "no sale" — honouring it would hand the dish
    // away free, which no bad edit should be able to do silently.
    expect(effectiveDishPrice({ price_aed: "20.00", sale_price_aed: "0" })).toBe(20);
    expect(effectiveDishPrice({ price_aed: "20.00", sale_price_aed: "-5" })).toBe(20);
    expect(isOnSale({ price_aed: "20.00", sale_price_aed: "0" })).toBe(false);
  });

  it("survives a non-numeric price rather than rendering NaN", () => {
    expect(effectiveDishPrice({ price_aed: "abc", sale_price_aed: null })).toBe(0);
    expect(isOnSale({ price_aed: "20.00", sale_price_aed: "abc" })).toBe(false);
  });

  it("formats money to two decimals", () => {
    expect(money(0.01)).toBe("0.01");
    expect(money(20)).toBe("20.00");
  });
});
