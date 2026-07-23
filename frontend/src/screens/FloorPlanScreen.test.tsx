import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { FloorPlanScreen } from "./FloorPlanScreen";

const TABLES = [
  { id: 1, label: "T01", seats: 4, status: "available", pos_x: 0, pos_y: 0 },
  {
    id: 2,
    label: "T02",
    seats: 2,
    status: "ordered",
    pos_x: 1,
    pos_y: 0,
    order_id: 55,
    order_total_aed: "86.00",
  },
];

/** Route the two GETs this screen makes: the table list and the floor layout. */
function stubApi(tables: unknown = TABLES) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(typeof input === "string" ? input : (input as Request).url ?? input);
      if (url.includes("/tables/layout")) {
        return Promise.resolve(
          new Response(JSON.stringify({ entrance_x: null, entrance_y: null }), { status: 200 }),
        );
      }
      if (url.includes("/tables")) {
        return Promise.resolve(new Response(JSON.stringify(tables), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({}), { status: 200 }));
    }),
  );
}

describe("FloorPlanScreen", () => {
  beforeEach(() => stubApi());
  afterEach(() => vi.restoreAllMocks());

  it("renders the floor canvas with the tables the API returns", async () => {
    renderWithProviders(<FloorPlanScreen />);
    expect(await screen.findByTestId("floor-plan-screen")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /floor plan/i })).toBeInTheDocument();
    expect(await screen.findByTestId("floor-canvas")).toBeInTheDocument();
    expect(await screen.findByTestId("table-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("floor-entrance")).toBeInTheDocument();
  });

  it("keeps the side pane hidden until layout edit mode is on", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FloorPlanScreen />);
    await user.click(await screen.findByTestId("table-card-1"));
    expect(screen.queryByTestId("order-pane")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("toggle-edit-layout"));
    expect(await screen.findByTestId("order-pane")).toBeInTheDocument();
    expect(screen.getByText(/table t01/i)).toBeInTheDocument();
  });

  it("exposes edit / delete only in layout edit mode", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FloorPlanScreen />);
    await screen.findByTestId("table-card-1");
    // Add table lives in the toolbar at all times; the per-table editor does not.
    expect(screen.getByTestId("add-table")).toBeInTheDocument();
    expect(screen.queryByTestId("delete-table")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("toggle-edit-layout"));
    await user.click(screen.getByTestId("table-card-1"));
    await waitFor(() => expect(screen.getByTestId("delete-table")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /edit table/i })).toBeInTheDocument();
  });

  it("asks for confirmation before removing a table", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FloorPlanScreen />);
    await screen.findByTestId("table-card-1");
    await user.click(screen.getByTestId("toggle-edit-layout"));
    await user.click(screen.getByTestId("table-card-1"));
    await user.click(await screen.findByTestId("delete-table"));
    expect(await screen.findByRole("alertdialog", { name: /remove t01/i })).toBeInTheDocument();
  });
});
