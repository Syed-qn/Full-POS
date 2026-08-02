import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearTaxConfigCache, fetchTaxConfig, splitVat } from "./useTaxConfig";

vi.mock("./apiClient", () => ({
  apiClient: { get: vi.fn() },
}));

const { apiClient } = await import("./apiClient");

describe("splitVat", () => {
  it("extracts VAT from an inclusive price", () => {
    const r = splitVat(26, { rate: 0.05, percent: 5, mode: "inclusive", ready: true });
    expect(r.gross).toBeCloseTo(26, 2);
    expect(r.net).toBeCloseTo(24.76, 2);
    expect(r.vat).toBeCloseTo(1.24, 2);
  });

  it("follows the rate it is given, not a hardcoded 5%", () => {
    const r = splitVat(26, { rate: 0.1, percent: 10, mode: "inclusive", ready: true });
    expect(r.net).toBeCloseTo(23.64, 2);
    expect(r.vat).toBeCloseTo(2.36, 2);
  });

  it("adds VAT on top in exclusive mode, so the customer pays more", () => {
    const r = splitVat(26, { rate: 0.1, percent: 10, mode: "exclusive", ready: true });
    expect(r.net).toBeCloseTo(26, 2);
    expect(r.vat).toBeCloseTo(2.6, 2);
    expect(r.gross).toBeCloseTo(28.6, 2);
  });

  it("charges nothing at a genuine 0% rate", () => {
    const r = splitVat(26, { rate: 0, percent: 0, mode: "inclusive", ready: true });
    expect(r.vat).toBe(0);
    expect(r.net).toBeCloseTo(26, 2);
  });
});

describe("fetchTaxConfig", () => {
  beforeEach(() => {
    clearTaxConfigCache();
    vi.mocked(apiClient.get).mockReset();
  });

  it("reads the rate and mode the server reports", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      vat_rate: "0.1000",
      vat_percent: 10,
      pricing_mode: "exclusive",
    });
    await expect(fetchTaxConfig()).resolves.toEqual({
      rate: 0.1,
      percent: 10,
      mode: "exclusive",
      ready: true,
    });
  });

  it("asks the server once and serves the rest from cache", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      vat_rate: "0.0500",
      vat_percent: 5,
      pricing_mode: "inclusive",
    });
    await fetchTaxConfig();
    await fetchTaxConfig();
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("refetches after the cache is dropped, so a saved rate reaches the till", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      vat_rate: "0.0500",
      vat_percent: 5,
      pricing_mode: "inclusive",
    });
    await fetchTaxConfig();
    clearTaxConfigCache();
    vi.mocked(apiClient.get).mockResolvedValue({
      vat_rate: "0.1000",
      vat_percent: 10,
      pricing_mode: "inclusive",
    });
    await expect(fetchTaxConfig()).resolves.toMatchObject({ percent: 10 });
  });

  it("charges nothing rather than guessing 5% on a nonsense response", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      vat_rate: "not-a-number",
      vat_percent: NaN,
      pricing_mode: "",
    });
    await expect(fetchTaxConfig()).resolves.toEqual({
      rate: 0,
      percent: 0,
      mode: "inclusive",
      ready: true,
    });
  });
});

describe("PENDING_TAX_CONFIG", () => {
  it("carries no rate, so nothing false can be printed before the server answers", async () => {
    const { PENDING_TAX_CONFIG } = await import("./useTaxConfig");
    expect(PENDING_TAX_CONFIG.ready).toBe(false);
    expect(PENDING_TAX_CONFIG.percent).toBe(0);
    expect(splitVat(26, PENDING_TAX_CONFIG).vat).toBe(0);
  });
});
