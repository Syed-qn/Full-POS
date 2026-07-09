import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MenuManagerScreen } from "./MenuManagerScreen";
import * as menuApi from "../lib/menuApi";

vi.mock("../lib/menuApi");

describe("MenuManagerScreen approval workflow", () => {
  beforeEach(() => {
    const menu = { id: 1, version: 1, status: "pending_confirmation", dishes: [] };
    vi.mocked(menuApi.fetchActiveMenu).mockResolvedValue(menu);
    // The screen re-fetches via getMenu once activeMenuId is set from fetchActiveMenu
    // (see the [activeMenuId, pending] effect) — mock it too, matching the convention
    // established in MenuManagerScreen.pricing.test.tsx.
    vi.mocked(menuApi.getMenu).mockResolvedValue(menu);
  });

  it("shows a Submit for Approval button on a draft menu", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><MenuManagerScreen /></MemoryRouter>
      </QueryClientProvider>,
    );
    const btn = await screen.findByRole("button", { name: /submit for approval/i });
    fireEvent.click(btn);
    await waitFor(() => expect(menuApi.submitMenuForApproval).toHaveBeenCalledWith(1));
  });
});
