import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { FloorPlanScreen } from "./FloorPlanScreen";

describe("FloorPlanScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200 })),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders floor plan smoke with zone tabs and mock tables when API empty", async () => {
    renderWithProviders(<FloorPlanScreen />);
    expect(await screen.findByTestId("floor-plan-screen")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /floor plan/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /main hall/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /patio/i })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("floor-mock-banner")).toBeInTheDocument());
    expect(screen.getByTestId("floor-table-grid")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new table order/i })).toBeInTheDocument();
  });

  it("opens selected table drawer on card click", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FloorPlanScreen />);
    const card = await screen.findByTestId("table-card--1");
    await user.click(card);
    expect(await screen.findByTestId("selected-table-drawer")).toBeInTheDocument();
    expect(screen.getByText(/status/i)).toBeInTheDocument();
  });

  it("shows transfer confirm when Transfer is pressed with a selection", async () => {
    const user = userEvent.setup();
    renderWithProviders(<FloorPlanScreen />);
    await user.click(await screen.findByTestId("table-card--1"));
    await user.click(screen.getByRole("button", { name: /^transfer$/i }));
    expect(await screen.findByRole("alertdialog", { name: /transfer/i })).toBeInTheDocument();
  });
});
