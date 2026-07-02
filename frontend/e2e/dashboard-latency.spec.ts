import { expect, test } from "@playwright/test";
import fixtureOrders from "../src/lib/fixtures/orders.json" with { type: "json" };

const CUSTOMERS = {
  items: [
    {
      id: 1,
      name: "Khalid Hassan",
      phone: "+971503334444",
      total_orders: 3,
      total_spend: "99.00",
      marketing_opted_in: true,
    },
  ],
  limit: 20,
  offset: 0,
};

const RIDERS = [
  { id: 1, name: "Ahmed Hassan", phone: "+971501111111", status: "available", on_duty: true },
];

async function stubDashboardApis(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ access_token: "e2e-token", token_type: "bearer" }),
    }),
  );
  await page.route("**/api/v1/onboarding/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ complete: true, has_menu: true, has_catalog_id: true }),
    }),
  );
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: 1, name: "E2E Resto", phone: "+9714", lat: 25.2, lng: 55.2, settings: {} }),
    }),
  );
  await page.route("**/api/v1/orders**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fixtureOrders),
    }),
  );
  await page.route("**/api/v1/ordering/customers**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(CUSTOMERS),
    }),
  );
  await page.route("**/api/v1/riders**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(RIDERS),
    }),
  );
  await page.route("**/api/v1/tickets**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
}

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Phone").fill("+97150000000");
  await page.getByLabel("Password").fill("password1");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page).toHaveURL("/");
}

test("sidebar navigation paints list rows within 400ms", async ({ page }) => {
  await stubDashboardApis(page);
  await login(page);

  const targets = [
    { link: "Orders", row: "Ali Hassan" },
    { link: "Customers", row: "Khalid Hassan" },
    { link: "Riders", row: "Ahmed Hassan" },
  ];

  for (const { link, row } of targets) {
    const start = Date.now();
    await page.getByRole("link", { name: link }).click();
    await expect(page.getByText(row)).toBeVisible({ timeout: 400 });
    const elapsed = Date.now() - start;
    expect(elapsed).toBeLessThan(400);
  }
});