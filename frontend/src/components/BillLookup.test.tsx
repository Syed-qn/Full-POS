import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BillLookup } from "./BillLookup";
import type { OrderOut } from "../lib/types";

const fetchOrders = vi.fn();
vi.mock("../lib/ordersApi", () => ({
  fetchOrders: (...args: unknown[]) => fetchOrders(...args),
}));

function order(over: Partial<OrderOut> = {}): OrderOut {
  return {
    id: 9,
    order_number: "R3-0009",
    daily_token: 8,
    status: "delivered",
    customer_name: "Walk-in",
    customer_phone: "0000000000",
    items: [],
    total_aed: "587.00",
    rider_id: null,
    rider_name: null,
    sla_started_at: null,
    prep_deadline: null,
    cook_estimate_minutes: null,
    created_at: "2026-07-30T08:00:00Z",
    address: null,
    lat: null,
    lng: null,
    order_type: "takeaway",
    table_id: null,
    ...over,
  } as OrderOut;
}

/** Shows where the lookup sent the browser — the whole point of the control. */
function Where() {
  const loc = useLocation();
  return <div data-testid="where">{`${loc.pathname}${loc.search}`}</div>;
}

function renderLookup() {
  return render(
    <MemoryRouter initialEntries={["/cashier/new-order?type=takeaway"]}>
      <BillLookup />
      <Routes>
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("BillLookup", () => {
  beforeEach(() => {
    fetchOrders.mockReset();
  });

  it("opens a take-away bill on the till by order id", async () => {
    fetchOrders.mockResolvedValue([order()]);
    renderLookup();

    await userEvent.type(screen.getByTestId("view-bill-input"), "R3-0009");
    await userEvent.click(screen.getByTestId("view-bill-search"));

    // ?order= is the door the till already uses to reopen an existing ticket.
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/cashier/new-order?type=takeaway&order=9&bill=R3-0009",
    );
  });

  it("looks a bare number up as a queue token, not a bill number", async () => {
    fetchOrders.mockResolvedValue([order()]);
    renderLookup();

    await userEvent.type(screen.getByTestId("view-bill-input"), "8");
    await userEvent.click(screen.getByTestId("view-bill-search"));

    // The token filter is server-side; searching q="8" would match any bill with
    // an 8 anywhere in it, which is not what the cashier typed.
    expect(fetchOrders).toHaveBeenCalledWith(expect.objectContaining({ token: 8 }));
  });

  it("sends a dine-in bill back through its table", async () => {
    // order_number must MATCH what is typed below: a dashed term is filtered
    // client-side against order_number, so a fixture numbered R3-0009 would be
    // discarded by a search for R3-0008 and the test would fail for that reason
    // rather than for the routing it is about.
    fetchOrders.mockResolvedValue([
      order({ order_number: "R3-0008", order_type: "dine_in", table_id: 4 }),
    ]);
    renderLookup();

    await userEvent.type(screen.getByTestId("view-bill-input"), "R3-0008");
    await userEvent.click(screen.getByTestId("view-bill-search"));

    // A dine-in tab hangs off the TABLE — ?order= drives only the takeaway till,
    // so reopening a dine-in bill by order id would land on an empty screen.
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/cashier/new-order?type=dine_in&table=4&bill=R3-0008",
    );
  });

  it("says so when nothing matches instead of failing silently", async () => {
    fetchOrders.mockResolvedValue([]);
    renderLookup();

    await userEvent.type(screen.getByTestId("view-bill-input"), "R9-9999");
    await userEvent.click(screen.getByTestId("view-bill-search"));

    expect(await screen.findByTestId("view-bill-message")).toBeInTheDocument();
    // ...and it must not have navigated anywhere.
    expect(screen.getByTestId("where")).toHaveTextContent("/cashier/new-order?type=takeaway");
  });

  it("offers a date picker when several months share one token", async () => {
    fetchOrders.mockResolvedValue([
      order({ id: 9, order_number: "R3-0009" }),
      order({ id: 3, order_number: "R3-0003", created_at: "2026-06-14T08:00:00Z" }),
    ]);
    renderLookup();

    await userEvent.type(screen.getByTestId("view-bill-input"), "8");
    await userEvent.click(screen.getByTestId("view-bill-search"));

    // The token resets each Dubai month, so one number can name several bills.
    const picker = await screen.findByTestId("view-bill-matches");
    expect(picker).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/cashier/new-order?type=takeaway");

    await userEvent.click(screen.getByText("R3-0003"));
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/cashier/new-order?type=takeaway&order=3&bill=8",
    );
  });

  it("refuses a dine-in bill with no table rather than opening an empty till", async () => {
    fetchOrders.mockResolvedValue([order({ order_type: "dine_in", table_id: null })]);
    renderLookup();

    await userEvent.type(screen.getByTestId("view-bill-input"), "R3-0007");
    await userEvent.click(screen.getByTestId("view-bill-search"));

    expect(await screen.findByTestId("view-bill-message")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/cashier/new-order?type=takeaway");
  });
});
