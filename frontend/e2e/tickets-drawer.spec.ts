import { expect, test } from "@playwright/test";

const ticket = {
  id: 1,
  customer_id: 2,
  customer_phone: "+971501112200",
  customer_name: "Test Customer",
  order_id: 86,
  source_message: "Food not good I want refund",
  evidence: [],
  category: "quality",
  status: "open",
  assigned_to: null,
  resolution_action: "none",
  resolution_amount_aed: null,
  replacement_order_id: null,
  resolution_note: null,
  resolved_at: null,
  created_at: "2026-06-29T10:00:00Z",
};

test.beforeEach(async ({ page }) => {
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
  await page.route("**/api/v1/tickets**", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([ticket]),
      });
    }
    return route.continue();
  });
  await page.route("**/api/v1/wallet/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        customer_id: 2,
        balance_aed: "0.00",
        available_aed: "0.00",
        status: "active",
      }),
    }),
  );
  await page.route("**/api/v1/orders", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );

  await page.goto("/login");
  await page.getByLabel("Phone").fill("+97150000000");
  await page.getByLabel("Password").fill("password1");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page).toHaveURL("/");
});

test("complaint drawer fields are editable and resolve works", async ({ page }) => {
  let resolveBody: unknown;
  await page.route("**/api/v1/tickets/1/resolve", async (route) => {
    resolveBody = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...ticket, status: "resolved", resolution_action: "resolved_no_action" }),
    });
  });

  await page.goto("/tickets");
  await page.getByText("Food not good I want refund").click();
  await expect(page.getByText("Complaint #1")).toBeVisible();

  const note = page.getByLabel(/resolution note/i);
  await note.click();
  await note.fill("Spoke with customer");
  await expect(note).toHaveValue("Spoke with customer");

  const markResolved = page.getByRole("button", { name: /mark resolved/i });
  await expect(markResolved).toBeEnabled();
  await markResolved.click();

  await expect.poll(() => resolveBody).toEqual({
    action: "resolved_no_action",
    note: "Spoke with customer",
  });
});

test("clicking inside the drawer does not close it via the scrim", async ({ page }) => {
  await page.goto("/tickets");
  await page.getByText("Food not good I want refund").click();
  await page.getByLabel(/resolution note/i).click();
  await expect(page.getByText("Complaint #1")).toBeVisible();
  await page.getByLabel(/refund amount/i).click();
  await expect(page.getByText("Complaint #1")).toBeVisible();
});

test("drawer inputs work on a narrow mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/tickets");
  // List row message is clipped on narrow viewports — open via the row button.
  await page.getByRole("button", { name: /#1.*open/i }).click();
  await expect(page.getByText("Complaint #1")).toBeVisible();
  const note = page.getByLabel(/resolution note/i);
  await note.click();
  await note.fill("Mobile note");
  await expect(note).toHaveValue("Mobile note");
  await expect(page.getByRole("button", { name: /mark resolved/i })).toBeEnabled();
});

test("shows API errors when resolve fails", async ({ page }) => {
  await page.route("**/api/v1/tickets/1/resolve", (route) =>
    route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({ detail: "original order not found" }),
    }),
  );
  await page.goto("/tickets");
  await page.getByRole("button", { name: /#1.*open/i }).click();
  await page.getByLabel(/resolution note/i).fill("trying");
  await page.getByRole("button", { name: /create replacement order/i }).click();
  await expect(page.getByText(/original order not found/i)).toBeVisible();
});

test("refund button stays disabled until amount and note are set", async ({ page }) => {
  await page.goto("/tickets");
  await page.getByText("Food not good I want refund").click();

  const refundBtn = page.getByRole("button", { name: /refund to wallet/i });
  await expect(refundBtn).toBeDisabled();

  await page.getByLabel(/resolution note/i).fill("Refund issued");
  await expect(refundBtn).toBeDisabled();

  await page.getByLabel(/refund amount/i).fill("25");
  await expect(refundBtn).toBeEnabled();
});