import { expect, test } from "@playwright/test";

const sampleCoupon = {
  id: 42,
  code: "SAVE-E2ETEST",
  kind: "multi_use",
  discount_type: "fixed",
  discount_aed: "15.00",
  percent: null,
  max_discount_aed: null,
  min_order_aed: "0.00",
  applies_to: "whole_order",
  per_customer_limit: null,
  total_redemption_limit: null,
  status: "active",
  valid_from: null,
  expires_at: null,
  created_at: "2026-06-29T10:00:00Z",
};

test("coupons page loads, creates coupon, shows in table", async ({ page }) => {
  let coupons: typeof sampleCoupon[] = [];

  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ access_token: "e2e-token", token_type: "bearer" }),
    }),
  );
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: 1, name: "E2E Resto", phone: "+9714", lat: 25.2, lng: 55.2, settings: {} }),
    }),
  );
  await page.route("**/api/v1/coupons**", async (route) => {
    if (route.request().method() === "POST") {
      coupons = [sampleCoupon];
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(sampleCoupon),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(coupons),
    });
  });

  await page.goto("/login");
  await page.getByLabel("Phone").fill("+97150000000");
  await page.getByLabel("Password").fill("password1");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await page.goto("/coupons");

  await expect(page.getByRole("heading", { name: "Coupons" })).toBeVisible();
  await expect(page.getByText(/no coupons yet/i)).toBeVisible();

  await page.getByLabel(/amount \(aed\)/i).fill("15");
  await page.getByRole("button", { name: /create coupon/i }).click();

  await expect(page.getByRole("cell", { name: "SAVE-E2ETEST" })).toBeVisible();
  await expect(page.getByText("Coupon created: SAVE-E2ETEST")).toBeVisible();
});