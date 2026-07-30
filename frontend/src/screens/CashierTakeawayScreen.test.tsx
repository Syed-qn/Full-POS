import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CashierTakeawayScreen } from "./CashierTakeawayScreen";
import type { OrderOut } from "../lib/types";

const fetchOrders = vi.fn();
const chargePayment = vi.fn();

vi.mock("../lib/ordersApi", () => ({
  fetchOrders: (...a: unknown[]) => fetchOrders(...a),
}));
vi.mock("../lib/paymentsApi", () => ({
  chargePayment: (...a: unknown[]) => chargePayment(...a),
}));
// The shared top bar pulls /me, the clock and a bill lookup — none of which this
// screen's behaviour depends on.
vi.mock("../components/WaiterTopBar", () => ({
  WaiterTopBar: () => null,
}));

function order(over: Partial<OrderOut> = {}): OrderOut {
  return {
    id: 3,
    order_number: "R1-0003",
    daily_token: 3,
    status: "ready",
    customer_name: "Walk-in",
    customer_phone: "0000000000",
    items: [{ dish_number: 10, name: "Chicken Club Sandwich", qty: 1, price_aed: "25.00" }],
    total_aed: "25.00",
    rider_id: null,
    rider_name: null,
    sla_started_at: null,
    prep_deadline: null,
    cook_estimate_minutes: null,
    created_at: "2026-07-30T09:44:00Z",
    address: null,
    lat: null,
    lng: null,
    order_type: "takeaway",
    table_id: null,
    ...over,
  } as OrderOut;
}

function renderScreen() {
  return render(
    <MemoryRouter initialEntries={["/cashier/takeaway"]}>
      <CashierTakeawayScreen />
    </MemoryRouter>,
  );
}

describe("CashierTakeawayScreen payment actions", () => {
  beforeEach(() => {
    fetchOrders.mockReset();
    chargePayment.mockReset();
  });

  it("offers Open Drawer and Other Pay on an order still owing money", async () => {
    // A take-away customer returns to the counter for the order the cashier is
    // looking at, so collecting has to be possible from HERE — it used to mean a
    // detour back to the till.
    fetchOrders.mockResolvedValue([order()]);
    renderScreen();

    expect(await screen.findByTestId("takeaway-open-drawer")).toBeInTheDocument();
    expect(screen.getByTestId("takeaway-other-pay")).toBeInTheDocument();
    expect(screen.getByTestId("takeaway-print-bill")).toBeInTheDocument();
  });

  it("hides both on a completed order so it cannot be charged twice", async () => {
    fetchOrders.mockResolvedValue([order({ status: "picked_up" })]);
    renderScreen();

    // The COMPLETED bucket has to be opened for the row to be selectable. The
    // filter chips are tablist tabs, not plain buttons.
    await userEvent.click(await screen.findByRole("tab", { name: /completed/i }));

    await waitFor(() =>
      expect(screen.getByTestId("takeaway-print-bill")).toBeInTheDocument(),
    );
    // Print Bill survives — a reprint takes no money.
    expect(screen.queryByTestId("takeaway-open-drawer")).not.toBeInTheDocument();
    expect(screen.queryByTestId("takeaway-other-pay")).not.toBeInTheDocument();
  });

  it("Open Drawer confirms first, then charges the order as cash", async () => {
    fetchOrders.mockResolvedValue([order()]);
    chargePayment.mockResolvedValue({});
    renderScreen();

    await userEvent.click(await screen.findByTestId("takeaway-open-drawer"));
    // A dialog, not an instant charge: the drawer opens and the cash is counted
    // before anything is recorded.
    const collect = await screen.findByTestId("takeaway-cod-collect");
    expect(chargePayment).not.toHaveBeenCalled();

    await userEvent.click(collect);
    await waitFor(() =>
      expect(chargePayment).toHaveBeenCalledWith(
        expect.objectContaining({
          order_id: 3,
          tender_type: "cash",
          amount_aed: "25.00",
        }),
      ),
    );
  });
});
