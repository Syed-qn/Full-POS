import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MenuManagerScreen } from "./MenuManagerScreen";
import * as menuApi from "../lib/menuApi";

vi.mock("../lib/menuApi");

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MenuManagerScreen />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MenuManagerScreen price rules", () => {
  beforeEach(() => {
    const menu = {
      id: 1, version: 1, status: "active",
      dishes: [{ id: 10, dish_number: 1, name: "Chai", price_aed: "3.00", category: "Drinks", description: null, is_available: true, whatsapp_enabled: true, variants: [], updated_at: "2026-07-09T00:00:00Z" }],
    };
    vi.mocked(menuApi.fetchActiveMenu).mockResolvedValue(menu);
    // The screen re-fetches via getMenu once activeMenuId is set from
    // fetchActiveMenu (see the [activeMenuId, pending] effect) — mock it too,
    // matching MenuManagerScreen.test.tsx's convention.
    vi.mocked(menuApi.getMenu).mockResolvedValue(menu);
    vi.mocked(menuApi.listPriceRules).mockResolvedValue([
      { id: 5, dish_id: 10, rule_type: "channel", price_aed: "5.00", channel: "aggregator", start_time: null, end_time: null, days_of_week: null },
    ]);
  });

  it("shows existing price rules for a dish and allows deleting one", async () => {
    renderScreen();
    fireEvent.click(await screen.findByText("Chai"));
    fireEvent.click(await screen.findByRole("button", { name: /price rules/i }));
    expect(await screen.findByText(/aggregator/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /delete rule/i }));
    await waitFor(() => expect(menuApi.deletePriceRule).toHaveBeenCalledWith(10, 5));
  });

  // Regression test for the "price rules panel unreachable behind the dish edit
  // modal's overlay" bug: the panel used to render as a position:fixed SIBLING of
  // the modal at a z-index below the modal overlay, so every click on it actually
  // landed on the overlay and closed the modal instead. jsdom performs no
  // layout/paint/stacking, so the only realistic assertion here is DOM structure:
  // the "Price rules" toggle must live INSIDE the modal's own DOM subtree (so it is
  // above the overlay by construction, not by z-index), not as a sibling of it.
  it("renders the price rules toggle inside the dish edit modal's DOM tree", async () => {
    renderScreen();
    fireEvent.click(await screen.findByText("Chai"));

    const modal = await screen.findByTestId("dish-edit-modal");
    const toggle = within(modal).getByRole("button", { name: /price rules/i });
    expect(modal).toContainElement(toggle);
  });
});
