import { expect, test } from "@playwright/test";
import fixtureOrders from "../src/lib/fixtures/orders.json" with { type: "json" };

const LIVE_MAP = {
  origin: { lat: 25.2, lng: 55.27, name: "E2E Resto" },
  batches: [],
  sla_rings: [],
};

const DISPATCH_KPIS = {
  batch_rate_pct: 42,
  avg_stops: 2.1,
  engine_fallback_pct: 0,
};

test("login → live ops renders KPI strip and feed", async ({ page }) => {
  // Stub auth + me; serve fixture orders (preview build is prod — no dev fallback on 404).
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ access_token: "e2e-token", token_type: "bearer" }) }),
  );
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 1, name: "E2E Resto", phone: "+9714", lat: 25.2, lng: 55.2, settings: {} }) }),
  );
  await page.route("**/api/v1/onboarding/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ complete: true, has_menu: true, has_catalog_id: true }),
    }),
  );
  await page.route("**/api/v1/orders**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixtureOrders) }),
  );
  await page.route("**/api/v1/tickets**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/dispatch/kpis**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(DISPATCH_KPIS),
    }),
  );
  await page.route("**/api/v1/dispatch/live-map**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(LIVE_MAP),
    }),
  );

  // Redesign login: email (not phone). domcontentloaded avoids hanging on heavy asset load.
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await expect(page.getByLabel("Email")).toBeVisible({ timeout: 15_000 });
  await page.getByLabel("Email").fill("e2e@example.com");
  await page.getByLabel("Password").fill("password1");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();

  await expect(page).toHaveURL("/");
  // Live Ops KPI + fixture feed (redesign: board lanes still show customer names)
  await expect(page.getByText("Orders Today")).toBeVisible();
  // Redesign: late orders appear on both the urgent strip and the Late board lane.
  await expect(page.getByText("Ali Hassan").first()).toBeVisible();

  // Redesign chrome: Daily nav group includes Floor Plan; TopBar has Alerts
  await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Floor Plan" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Live Ops" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Alert center/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live Ops" })).toBeVisible();
});
