import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { InventoryScreen } from "./InventoryScreen";

vi.mock("../lib/liveEvents", () => ({ subscribeLive: () => () => {} }));

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const INGREDIENTS = [
  {
    id: 1,
    name: "Chicken",
    unit: "kg",
    current_stock: "30.000",
    low_stock_threshold: "2.000",
    par_level: "40.000",
    cost_per_unit_aed: "18.0000",
  },
];

const INCOMING = {
  id: 7,
  status: "in_transit",
  direction: "in",
  from_restaurant_id: 2,
  from_branch_name: "Deira",
  to_restaurant_id: 1,
  to_branch_name: "Marina",
  dispatched_by: "manager",
  received_by: null,
  note: null,
  created_at: "2026-07-29T06:00:00",
  lines: [
    {
      ingredient_name: "Chicken",
      unit: "kg",
      qty_requested: null,
      quantity: "10.000",
      qty_received: null,
    },
  ],
};

/** Another branch asking THIS one for stock. Direction is the direction the
 *  stock will travel, so a request sits "out" on the holder's side. */
const REQUEST_TO_ME = {
  id: 9,
  status: "pending",
  direction: "out",
  from_restaurant_id: 1,
  from_branch_name: "Marina",
  to_restaurant_id: 2,
  to_branch_name: "Deira",
  dispatched_by: null,
  received_by: null,
  note: "before the dinner rush",
  created_at: "2026-07-29T07:00:00",
  lines: [
    {
      ingredient_name: "Chicken",
      unit: "kg",
      qty_requested: "10.000",
      quantity: "10.000",
      qty_received: null,
    },
  ],
};

/** Calls made, so a test can assert the body of the one it cares about. */
let calls: Array<{ path: string; method: string; body: unknown }>;

/** @param branches sibling branches this restaurant can send to. */
function mockApi(branches: Array<{ id: number; name: string }>, transfers: unknown[]) {
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

      // Order matters: the sibling list lives under the transfers prefix.
      if (path.includes("/branch-transfers/branches")) return Promise.resolve(json(branches));
      if (path.includes("/branch-transfers") && method === "POST") {
        return Promise.resolve(json({ id: 7, status: "completed" }));
      }
      if (path.includes("/branch-transfers")) return Promise.resolve(json(transfers));
      if (path.endsWith("/api/v1/ingredients")) return Promise.resolve(json(INGREDIENTS));
      // Not an array like the rest — the screen reads .rows off it.
      if (path.includes("/inventory-valuation")) {
        return Promise.resolve(json({ total_value_aed: "540.00", rows: [] }));
      }
      return Promise.resolve(json([]));
    }),
  );
}

describe("InventoryScreen — branch transfers", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
  });

  it("hides the tab entirely for a restaurant with no other branch", async () => {
    mockApi([], []);
    renderWithProviders(<InventoryScreen />);
    // Positive control: the tab bar rendered, so a missing Transfers tab means
    // hidden-on-purpose and not a screen that failed to load.
    await screen.findByRole("tab", { name: /^stock/i });
    expect(screen.queryByRole("tab", { name: /transfers/i })).toBeNull();
  });

  it("shows the tab and how many deliveries are waiting to be confirmed", async () => {
    mockApi([{ id: 2, name: "Deira" }], [INCOMING]);
    renderWithProviders(<InventoryScreen />);
    const tab = await screen.findByRole("tab", { name: /transfers/i });
    // The count is the point: until it is confirmed, that stock is in neither
    // branch's figures.
    expect(tab.textContent).toContain("1");
  });

  it("confirms a delivery that arrived in full with one click", async () => {
    mockApi([{ id: 2, name: "Deira" }], [INCOMING]);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /transfers/i }));
    await screen.findByText(/on the way from Deira/i);

    fireEvent.click(screen.getByRole("button", { name: /all arrived/i }));
    await waitFor(() => {
      const receive = calls.find((c) => c.path.includes("/7/receive"));
      expect(receive).toBeTruthy();
      // No lines means "everything as sent" — the server fills in the sent
      // quantities, so the ordinary case cannot be mistyped.
      expect(receive?.body).toEqual({ lines: [] });
    });
  });

  it("records a short delivery as what actually arrived", async () => {
    mockApi([{ id: 2, name: "Deira" }], [INCOMING]);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /transfers/i }));
    fireEvent.click(await screen.findByRole("button", { name: /something is missing/i }));

    fireEvent.change(screen.getByLabelText(/chicken received/i), { target: { value: "8" } });
    fireEvent.click(screen.getByRole("button", { name: /save what arrived/i }));

    await waitFor(() => {
      const receive = calls.find((c) => c.path.includes("/7/receive"));
      expect(receive?.body).toEqual({
        lines: [{ ingredient_name: "Chicken", qty_received: "8" }],
      });
    });
  });

  it("asks another branch for stock without moving any", async () => {
    mockApi([{ id: 2, name: "Deira" }], []);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /transfers/i }));
    // Asking is the default: the branch that runs out is the one that knows.
    fireEvent.change(await screen.findByLabelText(/ask which branch/i), {
      target: { value: "2" },
    });
    fireEvent.change(screen.getByLabelText(/^item$/i), { target: { value: "Chicken" } });
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /send request/i }));

    await waitFor(() => {
      const post = calls.find((c) => c.method === "POST" && c.path.includes("/requests"));
      expect(post).toBeTruthy();
      const body = post?.body as Record<string, unknown>;
      // from_restaurant_id is who you are ASKING; the asker is the token.
      expect(body.from_restaurant_id).toBe(2);
      expect(body.lines).toEqual([{ ingredient_name: "Chicken", quantity: "10" }]);
      // Nothing may hit dispatch — a request that quietly moved stock would let
      // any branch empty another's store by asking.
      expect(
        calls.some((c) => c.method === "POST" && c.path.endsWith("/api/v1/branch-transfers")),
      ).toBe(false);
    });
  });

  it("answers a request from another branch in one click", async () => {
    mockApi([{ id: 2, name: "Deira" }], [REQUEST_TO_ME]);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /transfers/i }));
    await screen.findByText(/Deira asked for/i);

    fireEvent.click(screen.getByRole("button", { name: /send it all/i }));
    await waitFor(() => {
      const post = calls.find((c) => c.path.includes("/9/approve"));
      expect(post).toBeTruthy();
      // No lines means "exactly what was asked for", so the ordinary answer
      // cannot be mistyped.
      expect(post?.body).toEqual({ lines: [] });
    });
  });

  it("sends less than was asked for, keeping the request on the record", async () => {
    mockApi([{ id: 2, name: "Deira" }], [REQUEST_TO_ME]);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /transfers/i }));
    fireEvent.click(await screen.findByRole("button", { name: /send less/i }));

    fireEvent.change(screen.getByLabelText(/chicken to send/i), { target: { value: "6" } });
    fireEvent.click(screen.getByRole("button", { name: /send this much/i }));

    await waitFor(() => {
      const post = calls.find((c) => c.path.includes("/9/approve"));
      expect(post?.body).toEqual({
        lines: [{ ingredient_name: "Chicken", quantity: "6" }],
      });
    });
  });

  it("counts requests to answer as well as deliveries to confirm", async () => {
    mockApi([{ id: 2, name: "Deira" }], [REQUEST_TO_ME, INCOMING]);
    renderWithProviders(<InventoryScreen />);
    const tab = await screen.findByRole("tab", { name: /transfers/i });
    // Both block another branch, so both belong on the tab and not behind it.
    expect(tab.textContent).toContain("2");
  });

  it("sends stock without ever naming the branch it comes from", async () => {
    mockApi([{ id: 2, name: "Deira" }], []);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /transfers/i }));
    fireEvent.click(await screen.findByRole("tab", { name: /send stock/i }));

    fireEvent.change(await screen.findByLabelText(/to branch/i), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText(/^item$/i), { target: { value: "Chicken" } });
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /^send$/i }));

    await waitFor(() => {
      const post = calls.find(
        (c) => c.method === "POST" && c.path.endsWith("/api/v1/branch-transfers"),
      );
      expect(post).toBeTruthy();
      const body = post?.body as Record<string, unknown>;
      expect(body.to_restaurant_id).toBe(2);
      expect(body.lines).toEqual([{ ingredient_name: "Chicken", quantity: "10" }]);
      // The sending branch comes from the token. A "from" in the body would be
      // a way to move another branch's stock.
      expect(Object.keys(body)).not.toContain("from_restaurant_id");
    });
  });
  it("pages past transfers five at a time", async () => {
    // Seven finished transfers: five on the first page, two on the second.
    const done = Array.from({ length: 7 }, (_, i) => ({
      ...INCOMING,
      id: 100 + i,
      status: "completed",
      lines: [
        {
          ingredient_name: `Item${i}`,
          unit: "kg",
          qty_requested: null,
          quantity: "1.000",
          qty_received: "1.000",
        },
      ],
    }));
    mockApi([{ id: 2, name: "Deira" }], done);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /transfers/i }));

    await screen.findByText(/1–5 of 7/);
    expect(screen.getByText(/Item0/)).toBeTruthy();
    expect(screen.queryByText(/Item5/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /^next$/i }));
    await screen.findByText(/6–7 of 7/);
    // The range, not "page 2 of 2" — when a transfer is missing you want to
    // know how far down the list you have read.
    expect(screen.getByText(/Item5/)).toBeTruthy();
    expect(screen.queryByText(/Item0/)).toBeNull();
  });

  it("hides the pager when everything fits on one page", async () => {
    mockApi([{ id: 2, name: "Deira" }], [{ ...INCOMING, id: 200, status: "completed" }]);
    renderWithProviders(<InventoryScreen />);
    fireEvent.click(await screen.findByRole("tab", { name: /transfers/i }));

    await screen.findByText(/past transfers/i);
    expect(screen.queryByRole("button", { name: /^next$/i })).toBeNull();
  });
});
