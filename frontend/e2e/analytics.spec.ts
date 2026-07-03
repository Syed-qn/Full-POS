import { expect, test } from "@playwright/test";

const DISPATCH_KPIS = {
  batch_rate_pct: 42,
  avg_stops: 2.1,
  engine_fallback_pct: 0,
  window: "24h",
};

test("login → reports page renders delivery, marketing, and forecast cards", async ({
  page,
}) => {
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
      body: JSON.stringify({
        id: 1,
        name: "E2E Resto",
        phone: "+9714",
        lat: 25.2,
        lng: 55.2,
        settings: {},
      }),
    }),
  );
  await page.route("**/api/v1/onboarding/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ complete: true, has_menu: true, has_catalog_id: true }),
    }),
  );
  await page.route("**/api/v1/orders**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: 1,
          customer_name: "E2E Customer",
          customer_phone: "+971500000099",
          status: "delivered",
          total_aed: "75.00",
          items: [],
          created_at: "2026-07-03T10:00:00Z",
          sla_started_at: null,
        },
      ]),
    }),
  );
  await page.route("**/api/v1/dispatch/kpis**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(DISPATCH_KPIS),
    }),
  );
  await page.route("**/api/v1/marketing/campaigns**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: 1,
          type: "promotional",
          status: "sent",
          stats: { sent: 20, converted: 3 },
          created_at: "2026-07-03T09:00:00Z",
        },
      ]),
    }),
  );
  await page.route("**/api/v1/predictions/latest**", (route) =>
    route.fulfill({ status: 404, body: "not found" }),
  );

  await page.goto("/login");
  await page.getByLabel("Phone").fill("+97150000000");
  await page.getByLabel("Password").fill("password1");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page).toHaveURL("/");

  await page.getByRole("link", { name: "Reports" }).click();
  await expect(page).toHaveURL("/analytics");
  await expect(page.getByRole("heading", { name: "Reports" })).toBeVisible();
  await expect(page.getByText("Delivery & Operations")).toBeVisible();
  await expect(page.getByText("Marketing Messages")).toBeVisible();
  await expect(page.getByText("Expected Orders Today")).toBeVisible();
  await expect(page.getByText(/batch rate/i)).toBeVisible();
  await expect(page.getByText("Campaigns sent")).toBeVisible();
});