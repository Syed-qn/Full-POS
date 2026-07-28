import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { InventoryScreen } from "./InventoryScreen";

// The screen has no Refresh button, so a live event is the only thing that
// brings new figures in. Capture the listener rather than opening a real
// stream: the point under test is what the screen does when told, not the
// transport, which liveEvents has its own tests for.
const live = vi.hoisted(() => ({ listeners: [] as Array<(e: unknown) => void> }));
vi.mock("../lib/liveEvents", () => ({
  subscribeLive: (fn: (e: unknown) => void) => {
    live.listeners.push(fn);
    return () => {
      const i = live.listeners.indexOf(fn);
      if (i >= 0) live.listeners.splice(i, 1);
    };
  },
}));

/** The page has sub navigation now, so a card lives on exactly one tab. */
function openTab(name: RegExp) {
  fireEvent.click(screen.getByRole("tab", { name }));
}

function emitLive(topic: string) {
  act(() => {
    for (const fn of [...live.listeners]) fn({ topic, restaurant_id: 1 });
  });
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("InventoryScreen", () => {
  beforeEach(() => {
    live.listeners.length = 0;
    localStorage.clear();
    localStorage.setItem("ops_token", "restaurant-token");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: unknown, init?: RequestInit) => {
        const path = String(url);
        if (path.endsWith("/api/v1/ingredients") && init?.method === "POST") {
          return Promise.resolve(
            json(
              {
                id: 3,
                name: "Mint",
                unit: "bunch",
                current_stock: "2.000",
                low_stock_threshold: "1.000",
                par_level: "8.000",
                cost_per_unit_aed: "0.5000",
              },
              201,
            ),
          );
        }
        if (path.endsWith("/api/v1/ingredients")) {
          return Promise.resolve(
            json([
              {
                id: 1,
                name: "Tomato",
                unit: "kg",
                current_stock: "5.000",
                low_stock_threshold: "2.000",
                par_level: "10.000",
                cost_per_unit_aed: "3.0000",
              },
              {
                id: 2,
                name: "Cheese",
                unit: "kg",
                current_stock: "1.000",
                low_stock_threshold: "2.000",
                par_level: "6.000",
                cost_per_unit_aed: "12.0000",
              },
            ]),
          );
        }
        if (path.includes("/inventory-valuation")) {
          return Promise.resolve(
            json({
              total_value_aed: "27.00",
              rows: [
                {
                  ingredient_id: 1,
                  ingredient_name: "Tomato",
                  unit: "kg",
                  current_stock: "5.000",
                  cost_per_unit_aed: "3.0000",
                  value_aed: "15.00",
                },
                {
                  ingredient_id: 2,
                  ingredient_name: "Cheese",
                  unit: "kg",
                  current_stock: "1.000",
                  cost_per_unit_aed: "12.0000",
                  value_aed: "12.00",
                },
              ],
            }),
          );
        }
        if (path.includes("/stock-adjustments/10/approve")) {
          return Promise.resolve(json({ id: 10, status: "approved" }));
        }
        if (path.includes("/stock-adjustments")) {
          return Promise.resolve(
            json([
              {
                id: 10,
                ingredient_id: 2,
                requested_qty: "4.000",
                previous_qty_snapshot: "1.000",
                reason: "closing count",
                status: "pending",
                requested_by: "cashier",
              },
            ]),
          );
        }
        if (path.includes("/low-stock-alert")) return Promise.resolve(json({ enqueued: true }));
        if (path.includes("/low-stock")) {
          return Promise.resolve(
            json([
              {
                id: 2,
                name: "Cheese",
                unit: "kg",
                current_stock: "1.000",
                low_stock_threshold: "2.000",
                par_level: "6.000",
                cost_per_unit_aed: "12.0000",
              },
            ]),
          );
        }
        if (path.includes("/reorder-suggestions")) {
          return Promise.resolve(
            json([
              {
                ingredient_id: 2,
                ingredient_name: "Cheese",
                current_stock: "1.000",
                par_level: "6.000",
                suggested_order_qty: "5.000",
              },
            ]),
          );
        }
        if (path.includes("/reports/variance")) {
          return Promise.resolve(
            json([
              {
                id: 1,
                ingredient_id: 1,
                ingredient_name: "Tomato",
                previous_stock: "30.000",
                counted_stock: "10.000",
                variance: "-20.000",
                counted_by: "manager",
                reason_code: "shrinkage",
                reason: null,
                variance_value_aed: "-60.00",
                // 20:02 UTC = 00:02 the NEXT day in Dubai (UTC+4). Naive, the
                // way SQLAlchemy actually serialises it.
                created_at: "2026-07-28T20:02:14.908209",
              },
            ]),
          );
        }
        if (path.includes("/reports/anomaly-alerts")) return Promise.resolve(json([]));
        if (path.includes("/reports/spoilage")) return Promise.resolve(json([]));
        if (path.includes("/reports/closing-history")) {
          return Promise.resolve(
            json([
              { closing_date: "2026-07-28", total_value_aed: "27.00", items: 2 },
              { closing_date: "2026-07-27", total_value_aed: "40.00", items: 2 },
            ]),
          );
        }
        if (path.includes("/reports/closing-snapshot")) {
          return Promise.resolve(json([{ ingredient_id: 1 }, { ingredient_id: 2 }]));
        }
        if (path.includes("/locations")) {
          return Promise.resolve(
            json([
              { id: 1, name: "Main branch", code: "branch", kitchen_role: "branch", is_active: true },
              { id: 2, name: "Central kitchen", code: "central", kitchen_role: "central", is_active: true },
              { id: 3, name: "Commissary", code: "commissary", kitchen_role: "commissary", is_active: true },
            ]),
          );
        }
        if (path.includes("/expiring-soon")) return Promise.resolve(json([]));
        if (path.endsWith("/api/v1/vendors") && init?.method === "POST") {
          return Promise.resolve(json({ id: 9, name: "Fresh Co", phone: "+9715000999" }, 201));
        }
        if (path.includes("/api/v1/vendors")) {
          return Promise.resolve(json([{ id: 5, name: "Spice Co", phone: "+9715000001" }]));
        }
        if (path.includes("/purchase-orders") && init?.method === "POST") {
          return Promise.resolve(
            json(
              {
                id: 40,
                vendor_id: 5,
                status: "draft",
                lines: [{ id: 1, ingredient_id: 1, qty_ordered: "5.000", unit_cost_aed: "1.0000" }],
              },
              201,
            ),
          );
        }
        if (path.includes("/purchase-orders") && path.includes("/receive")) {
          return Promise.resolve(json({ id: 40, vendor_id: 5, status: "received", lines: [] }));
        }
        if (path.includes("/purchase-orders")) {
          return Promise.resolve(
            json([
              {
                id: 40,
                vendor_id: 5,
                status: "draft",
                lines: [{ id: 1, ingredient_id: 1, qty_ordered: "5.000", unit_cost_aed: "1.0000" }],
              },
            ]),
          );
        }
        if (path.includes("/api/v1/grn")) {
          return Promise.resolve(
            json([{ id: 1, po_id: 40, grn_number: "GRN-3-0001", received_by: "manager" }]),
          );
        }
        if (path.includes("/waste")) {
          return Promise.resolve(
            json({
              id: 1,
              name: "Tomato",
              unit: "kg",
              current_stock: "4.000",
              low_stock_threshold: "2.000",
              par_level: "10.000",
              cost_per_unit_aed: "3.0000",
            }),
          );
        }
        if (path.includes("/restock")) {
          return Promise.resolve(
            json({
              id: 1,
              name: "Tomato",
              unit: "kg",
              current_stock: "6.000",
              low_stock_threshold: "2.000",
              par_level: "10.000",
              cost_per_unit_aed: "3.0000",
            }),
          );
        }
        if (path.includes("/stock-count")) {
          return Promise.resolve(
            json({
              variance: "-1.000",
              previous_stock: "5.000",
              counted_stock: "4.000",
              variance_pct: 20,
            }),
          );
        }
        if (path.includes("/batches")) {
          return Promise.resolve(
            json({
              id: 99,
              ingredient_id: 1,
              qty: "2.000",
              qty_remaining: "2.000",
              expiry_date: "2026-08-01",
              received_at: "2026-07-09T00:00:00Z",
            }, 201),
          );
        }
        if (path.includes("/staff/approvals") && init?.method === "POST") {
          return Promise.resolve(
            json({ id: 1, action_type: "stock_adjustment", status: "approved" }, 201),
          );
        }
        return Promise.resolve(json([]));
      }),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("shows valuation, low stock and suppliers", async () => {
    renderWithProviders(<InventoryScreen />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Inventory" })).toBeInTheDocument());
    expect(await screen.findByText("AED 27.00")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Tomato" })).toBeInTheDocument();
    expect(screen.getByText(/Cheese needs 5.000 kg/i)).toBeInTheDocument();

    openTab(/^purchasing$/i);
    // Twice on purpose: once naming the order's vendor, once in the supplier
    // list below it.
    expect(screen.getAllByText(/Spice Co/i).length).toBeGreaterThan(0);

    // No Locations tab: the three stock areas are auto-created and nothing
    // assigns stock to them, so it listed three names that did nothing.
    expect(screen.queryByRole("tab", { name: /^locations$/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Central kitchen/i)).not.toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/locations")),
    ).toHaveLength(0);
  });

  it("creates ingredients and sends low-stock alerts", async () => {
    renderWithProviders(<InventoryScreen />);

    await screen.findByRole("cell", { name: "Tomato" });
    // Adding is a dialog now: the six fields used once per ingredient no longer
    // sit permanently above the table you read every day.
    expect(screen.queryByLabelText("Ingredient name")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /new ingredient/i }));
    const addDialog = await screen.findByRole("dialog", { name: /new ingredient/i });
    fireEvent.change(within(addDialog).getByLabelText("Ingredient name"), { target: { value: "Mint" } });
    fireEvent.change(within(addDialog).getByLabelText("Unit"), { target: { value: "bunch" } });
    fireEvent.click(within(addDialog).getByRole("button", { name: /add ingredient/i }));
    await waitFor(() => expect(screen.getByRole("cell", { name: "Mint" })).toBeInTheDocument());

    // Stock adjustment approvals are gone. Nothing could ever reach that list:
    // /inventory is owner+manager, and the create-request endpoint 403s a
    // cashier PIN token, so the only people who could raise a request were the
    // same people who approve it — and they can record the count directly.
    openTab(/^counts/i);
    expect(screen.queryByRole("button", { name: /approve adjustment/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/stock adjustment approvals/i)).not.toBeInTheDocument();
    expect(
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes("/stock-adjustments")),
    ).toHaveLength(0);

    openTab(/^stock$/i);
    // One button, on the banner. The header used to carry a second copy of the
    // same action, which is only ever meaningful while the banner is showing.
    expect(screen.queryByRole("button", { name: /^low stock alert$/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /send whatsapp alert/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/ingredients/low-stock-alert"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("logs spoilage and creates a vendor/PO from the inventory screen", async () => {
    renderWithProviders(<InventoryScreen />);
    await screen.findByRole("cell", { name: "Tomato" });

    // The stock fields used to sit permanently above the table, showing every
    // field of every action at once. They live in a dialog now, and the dialog
    // only shows the fields the chosen action uses.
    expect(screen.queryByLabelText("Ops quantity")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^stock move$/i }));
    const moveDialog = await screen.findByRole("dialog", { name: /stock move/i });
    // Restock is the default, so the waste fields are not on screen yet.
    expect(within(moveDialog).queryByLabelText("Waste reason type")).not.toBeInTheDocument();
    fireEvent.click(within(moveDialog).getByRole("tab", { name: /waste/i }));
    fireEvent.change(within(moveDialog).getByLabelText("Ops ingredient"), { target: { value: "1" } });
    fireEvent.change(within(moveDialog).getByLabelText("Ops quantity"), { target: { value: "1.000" } });
    fireEvent.change(within(moveDialog).getByLabelText("Waste reason type"), {
      target: { value: "spoilage" },
    });
    fireEvent.click(within(moveDialog).getByRole("button", { name: /log waste/i }));
    // No manager PIN: /inventory is already an owner/manager screen, so the
    // gate asked whoever just signed in to prove they signed in, once per
    // stock move. The action runs straight away.
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/ingredients/1/waste"),
        expect.objectContaining({ method: "POST" }),
      ),
    );

    openTab(/^purchasing$/i);
    fireEvent.click(screen.getByRole("button", { name: /add vendor/i }));
    const vendorDialog = await screen.findByRole("dialog", { name: /new vendor/i });
    fireEvent.change(within(vendorDialog).getByLabelText("Vendor name"), {
      target: { value: "Fresh Co" },
    });
    fireEvent.click(within(vendorDialog).getByRole("button", { name: /^add vendor$/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/vendors"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("has no Refresh button and reloads when the branch reports a stock change", async () => {
    renderWithProviders(<InventoryScreen />);
    await screen.findByRole("cell", { name: "Tomato" });

    expect(screen.queryByRole("button", { name: /^refresh$/i })).not.toBeInTheDocument();
    expect(live.listeners.length).toBeGreaterThan(0);

    const before = vi.mocked(fetch).mock.calls.length;
    emitLive("inventory");
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(before));

    // Other topics are far busier than this one — an order event on every sale
    // would cost this page 13 requests each time for figures that did not move.
    const afterInventory = vi.mocked(fetch).mock.calls.length;
    emitLive("orders");
    emitLive("tables");
    expect(vi.mocked(fetch).mock.calls.length).toBe(afterInventory);
  });

  it("collapses a burst of events into one reload at a time", async () => {
    renderWithProviders(<InventoryScreen />);
    await screen.findByRole("cell", { name: "Tomato" });

    // Receiving a purchase order line by line fires several events within a
    // second. Overlapping reloads would multiply 13 requests by the burst size
    // for no extra freshness, so a load requested mid-flight is deferred to one
    // final run.
    const before = vi.mocked(fetch).mock.calls.length;
    for (let i = 0; i < 5; i += 1) emitLive("inventory");
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(before));
    // One load is 13 calls; five overlapping ones would be 65. Two sequential
    // loads (the first, plus the single deferred re-run) is the expected shape.
    expect(vi.mocked(fetch).mock.calls.length - before).toBeLessThanOrEqual(30);
  });

  it("shows a received order as ONE row naming the vendor, not two rows", async () => {
    renderWithProviders(<InventoryScreen />);
    await screen.findByRole("cell", { name: "Tomato" });
    openTab(/^purchasing$/i);

    // The PO and its goods received note used to render as two sibling rows,
    // so one order that had arrived read like two separate events.
    const po = await screen.findByText(/PO #40/i);
    const row = po.closest("div")?.parentElement as HTMLElement;
    expect(within(row).getByText(/GRN-3-0001/)).toBeInTheDocument();
    // Vendor name, not the database id it used to print.
    expect(po).toHaveTextContent(/Spice Co/);
    expect(screen.queryByText(/Vendor #5/)).not.toBeInTheDocument();
    // 5.000 x AED 1.0000
    expect(within(row).getByText(/AED 5\.00/)).toBeInTheDocument();
  });

  it("hides the recorded figures while a count is open, and sends the reason", async () => {
    renderWithProviders(<InventoryScreen />);
    await screen.findByRole("cell", { name: "Tomato" });

    // Visible before: the stock figure and the derived Low badge.
    expect(screen.getByText("5.000 kg")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^stock move$/i }));
    const dialog = await screen.findByRole("dialog", { name: /stock move/i });
    fireEvent.click(within(dialog).getByRole("tab", { name: /count/i }));

    // A counter who can read "5.000" types 5.000 and the variance is always
    // zero, which quietly disables the control the count exists to provide.
    expect(screen.queryByText("5.000 kg")).not.toBeInTheDocument();
    // The Low badge and the valuation are derived from stock, so they leak it
    // just as plainly.
    expect(screen.queryByText("Low")).not.toBeInTheDocument();
    expect(screen.queryByText("AED 27.00")).not.toBeInTheDocument();
    expect(screen.getByText(/blind count/i)).toBeInTheDocument();
    // Par and cost do not move with the count, so they stay readable.
    expect(screen.getByText("10.000 kg")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Ops ingredient"), { target: { value: "1" } });
    fireEvent.change(within(dialog).getByLabelText("Ops quantity"), { target: { value: "4.000" } });
    fireEvent.change(within(dialog).getByLabelText("Count reason"), {
      target: { value: "shrinkage" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /save count/i }));

    await waitFor(() => {
      const call = vi
        .mocked(fetch)
        .mock.calls.find(([url]) => String(url).includes("/stock-count"));
      expect(call).toBeTruthy();
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({
        counted_qty: "4.000",
        reason_code: "shrinkage",
      });
    });

    // Figures come back once the dialog closes.
    await waitFor(() => expect(screen.queryByText(/blind count/i)).not.toBeInTheDocument());
  });

  it("shows what the End of day snapshot button produced", async () => {
    renderWithProviders(<InventoryScreen />);
    await screen.findByRole("cell", { name: "Tomato" });
    openTab(/^counts/i);

    // The button was writing a row per ingredient per day that NO screen read
    // back, so pressing it looked like nothing happened.
    expect(await screen.findByText(/stock closing history/i)).toBeInTheDocument();
    expect(screen.getByText(/AED 27\.00/)).toBeInTheDocument();
    // Down from 40.00 the day before, shown as the change and not just a total.
    expect(screen.getByText(/AED 13\.00/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /end of day snapshot/i }));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/reports/closing-snapshot"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("dates a count by the real instant, not by reading UTC as local", async () => {
    // The server sends created_at with NO timezone marker even though it is
    // UTC. JavaScript reads a marker-less date-time as LOCAL, so a count taken
    // just after midnight Dubai showed the previous day.
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    renderWithProviders(<InventoryScreen />);
    await screen.findByRole("cell", { name: "Tomato" });
    openTab(/^counts/i);

    const expected = new Date("2026-07-28T20:02:14.908209Z").toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
    });
    const row = await screen.findByText(new RegExp(`counted 10\.000.*${expected}`));
    expect(row).toBeInTheDocument();
    // In a UTC+ timezone that instant belongs to the FOLLOWING day, which is
    // exactly the case the naive parse got wrong.
    if (new Date("2026-07-28T20:02:14.908209Z").getTimezoneOffset() < 0) {
      expect(expected).not.toBe("Jul 28");
    }
    expect(tz).toBeTruthy();
  });

  it("opens the stock move dialog on the row you clicked", async () => {
    renderWithProviders(<InventoryScreen />);
    await screen.findByRole("cell", { name: "Tomato" });

    // Cheese is the low-stock row, so its own button should arrive with Cheese
    // already chosen rather than making you find it in the list again.
    fireEvent.click(screen.getByRole("button", { name: /stock move for cheese/i }));
    const dialog = await screen.findByRole("dialog", { name: /stock move/i });
    expect(within(dialog).getByLabelText("Ops ingredient")).toHaveValue("2");
  });
});
