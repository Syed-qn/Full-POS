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

  it("asks WHICH BILL before joining AO1 into AO2, and does not merge both", async () => {
    // The user's report: AO1 shows "2 BILLS", they pick AO2 to keep the bill and
    // AO1 to join, hit Join — and nothing asks which of AO1's two parties is
    // moving. Merging both would put strangers' money on one invoice.
    renderFloor();
    await screen.findByTestId("cashier-table-2");

    await userEvent.click(screen.getByTestId("join-mode-toggle"));
    await userEvent.click(screen.getByTestId("cashier-table-3")); // AO2 keeps the bill
    await userEvent.click(screen.getByTestId("cashier-table-2")); // AO1 joins
    await userEvent.click(screen.getByTestId("join-confirm"));

    // The picker must appear, listing AO1's two bills...
    const dialog = await screen.findByTestId("table-bills-dialog");
    expect(dialog).toHaveTextContent("AO1");
    expect(screen.getByTestId("table-bill-24")).toBeInTheDocument();
    expect(screen.getByTestId("table-bill-25")).toBeInTheDocument();
    // ...and nothing may be merged until the question is answered.
    expect(joinTables).not.toHaveBeenCalled();
  });

  it("sends only the chosen party once the cashier answers", async () => {
    renderFloor();
    await screen.findByTestId("cashier-table-2");

    await userEvent.click(screen.getByTestId("join-mode-toggle"));
    await userEvent.click(screen.getByTestId("cashier-table-3"));
    await userEvent.click(screen.getByTestId("cashier-table-2"));
    await userEvent.click(screen.getByTestId("join-confirm"));
    await userEvent.click(await screen.findByTestId("table-bill-24"));

    await waitFor(() => expect(joinTables).toHaveBeenCalled());
    const [primaryId, tableIds, , fromOrderIds] = joinTables.mock.calls[0];
    expect(primaryId).toBe(3); // AO2 keeps the bill
    expect(tableIds).toEqual([2]); // AO1 joins
    expect(fromOrderIds).toEqual([24]); // only the party that was chosen
  });

  it("joins straight through when the joining table has a single bill", async () => {
    // AO2 has one bill, so there is nothing to ask — an extra tap here would be a
    // tax paid on the common case.
    renderFloor();
    await screen.findByTestId("cashier-table-2");

    await userEvent.click(screen.getByTestId("join-mode-toggle"));
    await userEvent.click(screen.getByTestId("cashier-table-2")); // AO1 keeps the bill
    await userEvent.click(screen.getByTestId("cashier-table-3")); // AO2 joins
    await userEvent.click(screen.getByTestId("join-confirm"));

    await waitFor(() => expect(joinTables).toHaveBeenCalled());
    expect(screen.queryByTestId("table-bills-dialog")).not.toBeInTheDocument();
  });
});
