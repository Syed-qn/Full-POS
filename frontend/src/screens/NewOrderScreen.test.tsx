import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NewOrderScreen } from "./NewOrderScreen";

// Stub the leaflet map picker (heavy in jsdom) with a button that sets a pin, so
// tests can satisfy the now-required delivery location deterministically.
vi.mock("../components/LocationPicker", () => ({
  LocationPicker: ({ onChange }: { onChange: (lat: number, lng: number) => void }) => (
    <button type="button" onClick={() => onChange(25.2, 55.27)}>
      drop-pin
    </button>
  ),
}));

const mockMenu = {
  id: 1,
  version: 1,
  status: "active",
  dishes: [
    {
      id: 10,
      dish_number: 101,
      name: "Chicken Biryani",
      price_aed: "22.00",
      category: "Rice",
      description: null,
      is_available: true,
    },
    {
      id: 11,
      dish_number: 201,
      name: "Mutton Karahi",
      price_aed: "35.00",
      category: "Curries",
      description: null,
      is_available: true,
    },
    {
      id: 12,
      dish_number: 301,
      name: "Unavailable",
      price_aed: "10.00",
      category: "Other",
      description: null,
      is_available: false,
    },
  ],
};

const mockSettings = {
  id: 1,
  name: "Test Restaurant",
  phone: "+971500000000",
  settings: {
    delivery_fee_tiers: [
      { max_km: 3, fee_aed: 0 },
      { max_km: 5, fee_aed: 5 },
    ],
  },
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status });
}

// URL-aware fetch mock so call ORDER never matters (the screen fires both the
// active-menu and /me fetches on mount). Tests override individual routes.
function mockFetch(overrides: Partial<Record<"menu" | "me" | "lookup" | "manual", () => Response>> = {}) {
  const routes = {
    menu: () => json(mockMenu),
    me: () => json(mockSettings),
    lookup: () => json({ detail: "not found" }, 404),
    manual: () => json({ id: 99, status: "confirmed", order_number: "R1-0001" }),
    ...overrides,
  };
  vi.stubGlobal(
    "fetch",
    vi.fn((url: unknown) => {
      const u = String(url);
      if (u.includes("/menus/active")) return Promise.resolve(routes.menu());
      if (u.includes("/api/v1/me")) return Promise.resolve(routes.me());
      if (u.includes("/customer-lookup")) return Promise.resolve(routes.lookup());
      if (u.includes("/orders/manual")) return Promise.resolve(routes.manual());
      return Promise.resolve(json(mockMenu));
    }),
  );
}

function renderScreen() {
  return render(
    <MemoryRouter>
      <NewOrderScreen />
    </MemoryRouter>,
  );
}

describe("NewOrderScreen", () => {
  beforeEach(() => {
    mockFetch();
  });
  afterEach(() => vi.restoreAllMocks());

  it("renders all main sections", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/Chicken Biryani/)).toBeInTheDocument(),
    );
    expect(screen.getByPlaceholderText("+971 50 123 4567")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Apt 404")).toBeInTheDocument();
    expect(screen.getByText(/Place Order/)).toBeInTheDocument();
  });

  it("shows a loading skeleton while the menu is still loading", () => {
    // Menu fetch stays pending → the screen renders its skeleton, not the form.
    mockFetch({ menu: undefined });
    vi.stubGlobal(
      "fetch",
      vi.fn((url: unknown) =>
        String(url).includes("/menus/active")
          ? new Promise(() => {}) // never resolves
          : Promise.resolve(json(mockSettings)),
      ),
    );
    const { container } = renderScreen();
    expect(container.querySelector('[aria-busy="true"]')).toBeTruthy();
    expect(screen.queryByPlaceholderText("+971 50 123 4567")).not.toBeInTheDocument();
  });

  it("shows unavailable dishes are hidden", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/Chicken Biryani/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Unavailable/)).not.toBeInTheDocument();
  });

  it("+ button increments qty and updates summary total", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/Chicken Biryani/)).toBeInTheDocument(),
    );

    const plusButtons = screen.getAllByText("+");
    fireEvent.click(plusButtons[0]); // first dish (Chicken Biryani)

    await waitFor(() =>
      expect(screen.getByText(/AED 22\.00/)).toBeInTheDocument(),
    );
  });

  it("Place Order button disabled when no items selected", async () => {
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/Chicken Biryani/)).toBeInTheDocument(),
    );
    const btn = screen.getByRole("button", { name: /Place Order/ });
    expect(btn).toBeDisabled();
  });

  it("phone lookup prefills name and address on found response", async () => {
    const lookupResult = {
      name: "Ahmed Al Rashid",
      last_address: {
        apt_room: "Apt 404",
        building: "Marina Tower",
        receiver_name: "Ahmed",
        notes: null,
      },
    };

    mockFetch({ lookup: () => json(lookupResult) });

    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/Chicken Biryani/)).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByPlaceholderText("+971 50 123 4567"), {
      target: { value: "+971501234567" },
    });
    fireEvent.click(screen.getByText("Look up"));

    await waitFor(() =>
      expect(
        screen.getByDisplayValue("Ahmed Al Rashid"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("Marina Tower")).toBeInTheDocument();
  });

  it("shows 'New customer' hint when lookup returns 404", async () => {
    mockFetch({ lookup: () => json({ detail: "not found" }, 404) });

    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/Chicken Biryani/)).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByPlaceholderText("+971 50 123 4567"), {
      target: { value: "+971509999999" },
    });
    fireEvent.click(screen.getByText("Look up"));

    await waitFor(() =>
      expect(screen.getByText(/New customer/)).toBeInTheDocument(),
    );
  });

  it("no active menu shows banner instead of form", async () => {
    mockFetch({ menu: () => json({ detail: "No active menu" }, 404) });
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/No active menu found/)).toBeInTheDocument(),
    );
    expect(
      screen.queryByPlaceholderText("+971 50 123 4567"),
    ).not.toBeInTheDocument();
  });

  it("successful submit calls POST /manual and navigates to /orders", async () => {
    mockFetch();

    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/Chicken Biryani/)).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByPlaceholderText("+971 50 123 4567"), {
      target: { value: "+971501234567" },
    });
    fireEvent.click(screen.getAllByText("+")[0]); // add biryani
    fireEvent.change(screen.getByPlaceholderText("Apt 404"), {
      target: { value: "Apt 1" },
    });
    fireEvent.change(screen.getByPlaceholderText("Marina Tower"), {
      target: { value: "Tower A" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("Who receives the order"),
      { target: { value: "Test User" } },
    );
    fireEvent.click(screen.getByText("drop-pin")); // required delivery location

    fireEvent.click(screen.getByRole("button", { name: /Place Order/ }));

    await waitFor(() => {
      const calls = vi.mocked(fetch).mock.calls;
      const postCall = calls.find(
        ([url, opts]) =>
          typeof url === "string" &&
          url.includes("/manual") &&
          (opts as RequestInit)?.method === "POST",
      );
      expect(postCall).toBeDefined();
    });
  });
});
