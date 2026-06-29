import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as menuApi from "../lib/menuApi";
import { MenuManagerScreen } from "./MenuManagerScreen";

vi.mock("../lib/menuApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/menuApi")>();
  return {
    ...actual,
    getMenu: vi.fn(),
    fetchActiveMenu: vi.fn(),
    setAvailability: vi.fn(),
  };
});

const activeMenu = {
  id: 5, version: 2, status: "active",
  dishes: [
    { id: 1, dish_number: 110, name: "Chicken Biryani", price_aed: "22.00", category: "Rice", description: null, is_available: true },
    { id: 2, dish_number: 201, name: "Mutton Karahi", price_aed: "35.00", category: "Curries", description: null, is_available: false },
  ],
};

const unifiedMenu = {
  menu_id: 5,
  catalog_id: "CAT1",
  items: [
    { link_status: "linked", dish_id: 1, catalog_product_id: 10, retailer_id: "rid-1", dish_number: 110, name: "Chicken Biryani", price_aed: 22, category: "Rice", description: null, is_available: true, catalog_active: true, image_url: null },
    { link_status: "dish_only", dish_id: 2, catalog_product_id: null, retailer_id: null, dish_number: 201, name: "Mutton Karahi", price_aed: 35, category: "Curries", description: null, is_available: false, catalog_active: null, image_url: null },
  ],
  linked_count: 1,
  dish_only_count: 1,
  catalog_only_count: 0,
};

const me = { id: 1, name: "Test Restaurant", phone: "+97141234567", lat: 25.2, lng: 55.3, settings: { catalog_id: "CAT1" } };

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status });
}

function mockFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: unknown, init?: RequestInit) => {
      const u = String(url);
      const method = (init?.method ?? "GET").toUpperCase();
      if (u.includes("/menu/unified") && method === "GET") {
        return Promise.resolve(json(unifiedMenu));
      }
      if (u.includes("/api/v1/me") && method === "GET") {
        return Promise.resolve(json(me));
      }
      if (u.includes("/menus/") && method === "GET") {
        return Promise.resolve(json(activeMenu));
      }
      if (u.includes("/availability")) {
        return Promise.resolve(json({ ...activeMenu.dishes[0], is_available: false }));
      }
      return Promise.resolve(json({}));
    }),
  );
}

describe("MenuManagerScreen", () => {
  beforeEach(() => {
    mockFetch();
    vi.mocked(menuApi.getMenu).mockResolvedValue(activeMenu);
    vi.mocked(menuApi.fetchActiveMenu).mockResolvedValue(activeMenu);
    vi.mocked(menuApi.setAvailability).mockResolvedValue({ ...activeMenu.dishes[0], is_available: false });
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders the active dish grid", async () => {
    render(<MenuManagerScreen initialMenuId={5} />);
    await waitFor(() => expect(screen.getAllByTestId("dish-card")).toHaveLength(2));
    expect(screen.getAllByText(/Mutton Karahi/).length).toBeGreaterThan(0);
    expect(menuApi.getMenu).toHaveBeenCalledWith(5);
  });

  it("shows a loading skeleton until the menu resolves", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    const { container } = render(<MenuManagerScreen initialMenuId={5} />);
    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
    expect(screen.queryByText("Upload your first menu to get started.")).not.toBeInTheDocument();
  });

  it("discovers the active menu on mount when no id is passed (route default)", async () => {
    render(<MenuManagerScreen />);
    await waitFor(() => expect(screen.getAllByText(/Chicken Biryani/).length).toBeGreaterThan(0));
    expect(screen.queryByText("Upload your first menu to get started.")).not.toBeInTheDocument();
  });

  it("toggles availability via API on switch click", async () => {
    render(<MenuManagerScreen initialMenuId={5} />);
    await waitFor(() => expect(screen.getAllByTestId("dish-card")).toHaveLength(2));
    const switches = screen.getAllByRole("switch");
    await userEvent.click(switches[0]);
    await waitFor(() => expect(menuApi.setAvailability).toHaveBeenCalled());
  });
});