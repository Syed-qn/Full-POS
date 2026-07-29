/** Creating a kitchen login.
 *
 * Waiters and cashiers each had a staff screen; the kitchen did not. The
 * sidebar's "Kitchen Management" pointed at /kitchens, which configures KDS
 * STATIONS, so there was no way to add a cook — and therefore nobody who could
 * sign in to the board the cooks are meant to use.
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { StaffScreen } from "./StaffScreen";
import { canAccess } from "../lib/navAccess";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const STAFF = [
  { id: 1, name: "Asfer (Waiter)", role: "waiter", phone: null, is_active: true },
  { id: 2, name: "Lacafe Kitchen", role: "kitchen", phone: null, is_active: true },
];

let calls: Array<{ path: string; method: string; body: unknown }>;

function mockApi() {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((url: unknown, init?: RequestInit) => {
      const path = String(url);
      const method = init?.method ?? "GET";
      let body: unknown = null;
      if (typeof init?.body === "string") {
        try {
          body = JSON.parse(init.body);
        } catch {
          body = init.body;
        }
      }
      calls.push({ path, method, body });
      if (path.includes("/api/v1/staff") && method === "POST") {
        return Promise.resolve(json({ id: 3, name: "Cook Sam", role: "kitchen" }, 201));
      }
      if (path.includes("/api/v1/staff")) return Promise.resolve(json(STAFF));
      return Promise.resolve(json([]));
    }),
  );
}

describe("StaffScreen — kitchen", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
    mockApi();
  });

  it("lists kitchen logins and not the waiters", async () => {
    renderWithProviders(<StaffScreen managedRole="kitchen" />);

    expect(await screen.findByText("Lacafe Kitchen")).toBeInTheDocument();
    // Each management screen owns one role; mixing them is how a cashier ends
    // up deleted from the waiter page.
    expect(screen.queryByText("Asfer (Waiter)")).toBeNull();
    expect(screen.getAllByRole("heading", { name: /kitchen management/i }).length).toBeGreaterThan(0);
  });

  it("creates the login with role kitchen, so it lands on the board", async () => {
    renderWithProviders(<StaffScreen managedRole="kitchen" />);
    await screen.findByText("Lacafe Kitchen");

    fireEvent.click(screen.getByRole("button", { name: /add kitchen login/i }));
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: "Cook Sam" } });
    fireEvent.change(screen.getByLabelText(/pin/i), { target: { value: "3391" } });
    fireEvent.click(screen.getByRole("button", { name: /^add kitchen login$|^save$|^create$/i }));

    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST" && c.path.includes("/api/v1/staff"));
      expect(post).toBeTruthy();
      // The role is what sends them to /kds and what the server checks before
      // refusing every manager endpoint. Anything else here and the cook gets
      // a login to the wrong screen.
      expect((post?.body as Record<string, unknown>)?.role).toBe("kitchen");
    });
  });

  it("has no shift, training or phone — it is a terminal, not a person", async () => {
    renderWithProviders(<StaffScreen managedRole="kitchen" />);
    await screen.findByText("Lacafe Kitchen");

    // Nobody clocks a screen in, a shared board has no trainee, and there is
    // no number to ring a pass on.
    expect(screen.queryByRole("switch", { name: /shift for/i })).toBeNull();
    expect(screen.queryByRole("switch", { name: /training mode for/i })).toBeNull();
    expect(screen.queryByRole("columnheader", { name: /^phone$/i })).toBeNull();
    // Positive control: the row rendered and the columns that DO apply stayed.
    expect(screen.getByRole("columnheader", { name: /^status$/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /^name$/i })).toBeInTheDocument();
  });

  it("keeps shift and training for a waiter, who is a person", async () => {
    renderWithProviders(<StaffScreen managedRole="waiter" />);
    await screen.findByText("Asfer (Waiter)");

    // The columns were hidden for one role, not deleted for everyone.
    expect(screen.getByRole("switch", { name: /shift for/i })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /training mode for/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /^phone$/i })).toBeInTheDocument();
  });

  it("keeps edit and remove on one line", async () => {
    renderWithProviders(<StaffScreen managedRole="kitchen" />);
    await screen.findByText("Lacafe Kitchen");

    const edit = screen.getByTestId("kitchen-edit-2");
    const remove = screen.getByTestId("kitchen-delete-2");
    // Both in the one flex row. Whether that row WRAPS is a stylesheet
    // question and jsdom does not apply CSS modules, so asserting on
    // getComputedStyle here would pass against an empty string and prove
    // nothing — the nowrap itself is only verifiable in the browser.
    expect(edit.parentElement).toBe(remove.parentElement);
    expect(edit.parentElement?.className).toMatch(/rowActions/);
  });

  it("is an owner/manager screen — the kitchen cannot mint its own login", () => {
    expect(canAccess("/kitchen-staff", "kitchen")).toBe(false);
    expect(canAccess("/kitchen-staff", "cashier")).toBe(false);
    // Positive control: the people who hire cooks still get in.
    expect(canAccess("/kitchen-staff", "manager")).toBe(true);
    expect(canAccess("/kitchen-staff", null)).toBe(true);
  });
});
