import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MenuManagerScreen } from "./MenuManagerScreen";

const activeMenu = {
  id: 5, version: 2, status: "active",
  dishes: [
    { id: 1, dish_number: 110, name: "Chicken Biryani", price_aed: "22.00", category: "Rice", description: null, is_available: true },
    { id: 2, dish_number: 201, name: "Mutton Karahi", price_aed: "35.00", category: "Curries", description: null, is_available: false },
  ],
};

describe("MenuManagerScreen", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/menus/5") && (!init || init.method === "GET")) {
        return Promise.resolve(new Response(JSON.stringify(activeMenu), { status: 200 }));
      }
      if (typeof url === "string" && url.includes("/availability")) {
        return Promise.resolve(new Response(JSON.stringify({ ...activeMenu.dishes[0], is_available: false }), { status: 200 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    }));
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the active dish grid", async () => {
    render(<MenuManagerScreen initialMenuId={5} />);
    await waitFor(() => expect(screen.getByText("Chicken Biryani")).toBeInTheDocument());
    expect(screen.getByText("Mutton Karahi")).toBeInTheDocument();
  });

  it("discovers the active menu on mount when no id is passed (route default)", async () => {
    // The /menu route renders <MenuManagerScreen /> with NO initialMenuId.
    // It must call GET /menus/active and show the dishes, not the empty state.
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (typeof url === "string" && url.includes("/menus/active") && (!init || init.method === "GET")) {
        return Promise.resolve(new Response(JSON.stringify(activeMenu), { status: 200 }));
      }
      if (typeof url === "string" && url.includes("/menus/5")) {
        return Promise.resolve(new Response(JSON.stringify(activeMenu), { status: 200 }));
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    }));
    render(<MenuManagerScreen />);
    await waitFor(() => expect(screen.getByText("Chicken Biryani")).toBeInTheDocument());
    expect(screen.queryByText("Upload your first menu to get started.")).not.toBeInTheDocument();
  });

  it("toggles availability via API on switch click", async () => {
    const fetchSpy = vi.mocked(fetch);
    render(<MenuManagerScreen initialMenuId={5} />);
    await waitFor(() => screen.getByText("Chicken Biryani"));
    const switches = screen.getAllByRole("switch");
    await userEvent.click(switches[0]);
    await waitFor(() =>
      expect(fetchSpy.mock.calls.some(([u]) => String(u).includes("/availability"))).toBe(true),
    );
  });
});
