/**
 * Role landings smoke (R6) — stubs staff PIN login; asserts home + chrome per role.
 * Does not require live API.
 */
import { expect, test } from "@playwright/test";

const ME = {
  id: 1,
  name: "E2E Resto",
  phone: "+9714",
  lat: 25.2,
  lng: 55.2,
  settings: {},
};

const ONBOARDING = { complete: true, has_menu: true, has_catalog_id: true };

async function stubCommon(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(ME) }),
  );
  await page.route("**/api/v1/onboarding/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ONBOARDING),
    }),
  );
  await page.route("**/api/v1/tickets**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/orders**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/menus/active**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: 1, version: 1, status: "active", dishes: [] }),
    }),
  );
  await page.route("**/api/v1/kds/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/dispatch/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" }),
  );
  await page.route("**/api/v1/floor/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
}

async function staffPinLogin(
  page: import("@playwright/test").Page,
  role: string,
  staffId = 7,
) {
  await page.route("**/api/v1/staff/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access_token: `e2e-${role}`,
        token_type: "bearer",
        role,
        staff_id: staffId,
        name: `E2E ${role}`,
        training_mode: false,
      }),
    }),
  );

  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.getByRole("tab", { name: /staff pin/i }).click();
  await page.getByLabel(/staff id/i).fill(String(staffId));
  for (const d of ["1", "2", "3", "4"]) {
    await page.getByRole("button", { name: `Digit ${d}` }).click();
  }
  await page.getByRole("button", { name: /sign in with pin/i }).click();
}

test("waiter PIN lands on floor; no payments nav", async ({ page }) => {
  await stubCommon(page);
  await staffPinLogin(page, "waiter");
  await expect(page).toHaveURL(/\/floor/);
  // Waiter may have limited nav — Payments should be hidden
  await expect(page.getByRole("link", { name: "Payments" })).toHaveCount(0);
});

test("cashier PIN lands on new-order terminal", async ({ page }) => {
  await stubCommon(page);
  await staffPinLogin(page, "cashier");
  await expect(page).toHaveURL(/\/new-order/);
  await expect(page.getByRole("heading", { name: /cashier terminal/i })).toBeVisible({
    timeout: 15_000,
  });
});

test("kitchen PIN lands on kds without main sidebar", async ({ page }) => {
  await stubCommon(page);
  await staffPinLogin(page, "kitchen");
  await expect(page).toHaveURL(/\/kds/);
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
});

test("owner email lands on live ops with settings", async ({ page }) => {
  await stubCommon(page);
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ access_token: "e2e-owner", token_type: "bearer" }),
    }),
  );
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Email").fill("owner@example.com");
  await page.getByLabel("Password").fill("password1");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("link", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live Ops" })).toBeVisible();
});
