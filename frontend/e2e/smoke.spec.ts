import { expect, test } from "@playwright/test";
import fixtureOrders from "../src/lib/fixtures/orders.json" with { type: "json" };

test("login → live ops renders KPI strip and feed", async ({ page }) => {
  // Stub auth + me; serve fixture orders (preview build is prod — no dev fallback on 404).
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ access_token: "e2e-token", token_type: "bearer" }) }),
  );
  await page.route("**/api/v1/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: 1, name: "E2E Resto", phone: "+9714", lat: 25.2, lng: 55.2, settings: {} }) }),
  );
  await page.route("**/api/v1/orders", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(fixtureOrders) }),
  );

  await page.goto("/login");
  await page.getByLabel("Phone").fill("+97150000000");
  await page.getByLabel("Password").fill("password1");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByText("Orders Today")).toBeVisible();
  await expect(page.getByText("Ali Hassan")).toBeVisible();
});
