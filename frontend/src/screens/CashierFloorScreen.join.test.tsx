import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CashierFloorScreen } from "./CashierFloorScreen";

const listTables = vi.fn();
const joinTables = vi.fn();

vi.mock("../lib/apiClient", () => ({
  apiClient: { get: (...a: unknown[]) => listTables(...a) },
}));
vi.mock("../lib/floorApi", () => ({
  fetchFloorLayout: () => Promise.resolve({ entrance_x: null, entrance_y: null }),
  joinTables: (...a: unknown[]) => joinTables(...a),
  unjoinTable: vi.fn(),
  // The bill picker renders through this — keep the real numbering rule so the
  // test reads the same labels a cashier would.
  billName: (b: { guest_label?: string | null }, i: number) =>
    b.guest_label?.trim() && !/^bill\s*\d+$/i.test(b.guest_label.trim())
      ? b.guest_label.trim()
      : `Bill ${i + 1}`,
}));
vi.mock("../lib/useLiveRefresh", () => ({ useLiveRefresh: () => {} }));
vi.mock("../components/WaiterTopBar", () => ({ WaiterTopBar: () => null }));
vi.mock("../components/Toaster", () => ({ toast: vi.fn() }));

// The floor auto-fits its grid unit to the canvas width. jsdom has no
// ResizeObserver, and without it the layout effect throws before anything renders.
class NoopResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
  NoopResizeObserver;

/** AO1 seats TWO parties (2 bills); AO2 seats one. Exactly the user's floor. */
const FLOOR = [
  {
    id: 2,
    label: "AO1",
    seats: 12,
    status: "ordered",
    pos_x: 1.5,
    pos_y: 1,
    order_id: 25,
    order_total_aed: "0.01",
    bill_count: 2,
    bills: [
      { order_id: 24, order_number: "R1-0014", daily_token: 13, total_aed: "26.00" },
      { order_id: 25, order_number: "R1-0015", daily_token: 14, total_aed: "0.01" },
    ],
    guests: 2,
  },
  {
    id: 3,
    label: "AO2",
    seats: 12,
    status: "ordered",
    pos_x: 4,
    pos_y: 1,
    order_id: 30,
    order_total_aed: "25.00",
    bill_count: 1,
    bills: [
      { order_id: 30, order_number: "R1-0016", daily_token: 15, total_aed: "25.00" },
    ],
    guests: 2,
  },
  // A free table — nothing to ask about when it is pulled into a group.
  {
    id: 4,
    label: "T01",
    seats: 4,
    status: "available",
    pos_x: 2.5,
    pos_y: 3,
    order_id: null,
    bill_count: 0,
    bills: [],
  },
];

function renderFloor(path = "/cashier/floor") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <CashierFloorScreen />
    </MemoryRouter>,
  );
}

describe("CashierFloorScreen — joining a table that seats two parties", () => {
  beforeEach(() => {
    listTables.mockReset();
    joinTables.mockReset();
    listTables.mockResolvedValue(FLOOR);
    joinTables.mockResolvedValue(FLOOR);
  });

  it("asks WHICH BILL the moment a two-party table is tapped", async () => {
    // The question belongs at SELECTION. Held until the Join button, the cashier
    // picks their tables, presses Join, and only then gets asked about a table
    // they had already moved on from — which is what they reported as "not
    // asking", because nothing happens at the moment they expect it to.
    renderFloor();
    await screen.findByTestId("cashier-table-2");

    await userEvent.click(screen.getByTestId("join-mode-toggle"));
    await userEvent.click(screen.getByTestId("cashier-table-3")); // AO2 keeps the bill
    await userEvent.click(screen.getByTestId("cashier-table-2")); // AO1 — two parties

    // Asked immediately, with no Join press in between.
    const dialog = await screen.findByTestId("table-bills-dialog");
    expect(dialog).toHaveTextContent("AO1");
    expect(screen.getByTestId("table-bill-24")).toBeInTheDocument();
    expect(screen.getByTestId("table-bill-25")).toBeInTheDocument();
    expect(joinTables).not.toHaveBeenCalled();
  });

  it("selects the table once its bill is chosen, then joins on confirm", async () => {
    renderFloor();
    await screen.findByTestId("cashier-table-2");

    await userEvent.click(screen.getByTestId("join-mode-toggle"));
    await userEvent.click(screen.getByTestId("cashier-table-3"));
    await userEvent.click(screen.getByTestId("cashier-table-2"));
    await userEvent.click(await screen.findByTestId("table-bill-24"));

    // Answering adds the table to the selection — the cashier can carry on
    // picking, and Join is a plain submit with no question left in it.
    expect(screen.queryByTestId("table-bills-dialog")).not.toBeInTheDocument();
    await userEvent.click(await screen.findByTestId("join-confirm"));

    await waitFor(() => expect(joinTables).toHaveBeenCalled());
    const [primaryId, tableIds, , fromOrderIds] = joinTables.mock.calls[0];
    expect(primaryId).toBe(3); // AO2 keeps the bill
    expect(tableIds).toEqual([2]); // AO1 joins
    expect(fromOrderIds).toEqual([24]); // only the party that was chosen
  });

  it("asks about the BILL-KEEPING table too when it is the split one", async () => {
    // Tapped first, AO1 keeps the bill — so the question is which of its bills IS
    // the group invoice, and that goes to the server as into_order_id, not as a
    // party travelling in.
    renderFloor();
    await screen.findByTestId("cashier-table-2");

    await userEvent.click(screen.getByTestId("join-mode-toggle"));
    await userEvent.click(screen.getByTestId("cashier-table-2")); // AO1 first
    await userEvent.click(await screen.findByTestId("table-bill-25"));
    await userEvent.click(screen.getByTestId("cashier-table-3")); // AO2 joins
    await userEvent.click(screen.getByTestId("join-confirm"));

    await waitFor(() => expect(joinTables).toHaveBeenCalled());
    const [primaryId, tableIds, intoOrderId, fromOrderIds] = joinTables.mock.calls[0];
    expect(primaryId).toBe(2);
    expect(tableIds).toEqual([3]);
    expect(intoOrderId).toBe(25);
    expect(fromOrderIds).toEqual([]);
  });

  it("never asks when no picked table seats more than one party", async () => {
    // AO2 has one bill and T01 has none, so there is nothing to ask — an extra tap
    // here would be a tax paid on the common case to serve the rare one.
    renderFloor();
    await screen.findByTestId("cashier-table-3");

    await userEvent.click(screen.getByTestId("join-mode-toggle"));
    await userEvent.click(screen.getByTestId("cashier-table-3")); // AO2 keeps the bill
    await userEvent.click(screen.getByTestId("cashier-table-4")); // T01 joins
    expect(screen.queryByTestId("table-bills-dialog")).not.toBeInTheDocument();

    await userEvent.click(screen.getByTestId("join-confirm"));
    await waitFor(() => expect(joinTables).toHaveBeenCalled());
    const [primaryId, tableIds, intoOrderId, fromOrderIds] = joinTables.mock.calls[0];
    expect(primaryId).toBe(3);
    expect(tableIds).toEqual([4]);
    expect(intoOrderId).toBeNull();
    expect(fromOrderIds).toEqual([]);
  });
});
