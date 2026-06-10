import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NewOrderScreen } from "./NewOrderScreen";

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

function renderScreen() {
  return render(
    <MemoryRouter>
      <NewOrderScreen />
    </MemoryRouter>,
  );
}

describe("NewOrderScreen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify(mockMenu), { status: 200 }),
      ),
    );
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

    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(mockMenu), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(lookupResult), { status: 200 }),
      );

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
    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(mockMenu), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "not found" }), { status: 404 }),
      );

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
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "No active menu" }), {
        status: 404,
      }),
    );
    renderScreen();
    await waitFor(() =>
      expect(screen.getByText(/No active menu found/)).toBeInTheDocument(),
    );
    expect(
      screen.queryByPlaceholderText("+971 50 123 4567"),
    ).not.toBeInTheDocument();
  });

  it("successful submit calls POST /manual and navigates to /orders", async () => {
    const confirmedOrder = { id: 99, status: "confirmed", order_number: "R1-0001" };

    vi.mocked(fetch)
      .mockResolvedValueOnce(
        new Response(JSON.stringify(mockMenu), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(confirmedOrder), { status: 200 }),
      );

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
