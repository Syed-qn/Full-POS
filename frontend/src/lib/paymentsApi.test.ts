import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  chargePayment,
  createPaymentLink,
  getBillingSettings,
  issueGiftCard,
  listPaymentLinks,
  openCashDrawer,
} from "./paymentsApi";

function respondJson(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("paymentsApi", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
    fetchMock = vi.fn().mockImplementation(() => respondJson({}));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.restoreAllMocks());

  it("hits category-5 payment endpoints", async () => {
    await getBillingSettings();
    await chargePayment({
      order_id: 1,
      tender_type: "tap_to_pay",
      amount_aed: "12.00",
      terminal_id: "t1",
    });
    await createPaymentLink(1, "12.00");
    await listPaymentLinks();
    await issueGiftCard({ amount_aed: "50", pin: "1234" });
    await openCashDrawer("100.00");

    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      "/api/v1/payments/billing-settings",
      "/api/v1/payments/charge",
      "/api/v1/payments/links",
      "/api/v1/payments/links",
      "/api/v1/gift-cards/issue",
      "/api/v1/cash-drawer/sessions",
    ]);
  });
});
