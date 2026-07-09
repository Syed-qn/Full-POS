import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as channelsApi from "../lib/channelsApi";
import { PublicStoreScreen } from "./PublicStoreScreen";

vi.mock("../lib/channelsApi", async (importOriginal) => {
  const actual = await importOriginal<typeof channelsApi>();
  return {
    ...actual,
    fetchPublicStoreMenu: vi.fn(),
    placePublicStoreOrder: vi.fn(),
  };
});

const menu = [
  {
    id: 1,
    name: "Chicken Shawarma",
    description: "Grilled wraps",
    price_aed: "18.00",
    category: "Mains",
    is_available: true,
  },
  {
    id: 2,
    name: "Fresh Juice",
    description: "Orange",
    price_aed: "12.00",
    category: "Drinks",
    is_available: true,
  },
];

function renderStore(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/order/:slug" element={<PublicStoreScreen />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PublicStoreScreen", () => {
  beforeEach(() => {
    vi.mocked(channelsApi.fetchPublicStoreMenu).mockReset();
    vi.mocked(channelsApi.placePublicStoreOrder).mockReset();
    vi.mocked(channelsApi.fetchPublicStoreMenu).mockResolvedValue(menu);
  });

  it("renders mobile storefront with sticky cart bar and large add buttons", async () => {
    renderStore("/order/demo-cafe");
    expect(await screen.findByText("Chicken Shawarma")).toBeInTheDocument();
    expect(screen.getByTestId("cart-bar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Chicken Shawarma" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add Chicken Shawarma" }));
    expect(screen.getByTestId("cart-bar")).toHaveTextContent("1 item");
  });

  it("locks table banner when table query param is present", async () => {
    renderStore("/order/demo-cafe?table=7&table_label=Patio%207");
    expect(await screen.findByTestId("table-lock-banner")).toBeInTheDocument();
    expect(screen.getByTestId("table-lock-banner")).toHaveTextContent("Patio 7");
    expect(screen.getByTestId("table-lock-banner")).toHaveTextContent("cannot change");
    expect(channelsApi.fetchPublicStoreMenu).toHaveBeenCalledWith("demo-cafe", "qr");
  });

  it("opens cart sheet and places order", async () => {
    vi.mocked(channelsApi.placePublicStoreOrder).mockResolvedValue({
      id: 9,
      order_number: "R1-0009",
      status: "confirmed",
      source_channel: "website",
      total_aed: "18.00",
    });
    renderStore("/order/demo-cafe");
    await screen.findByText("Chicken Shawarma");
    fireEvent.click(screen.getByRole("button", { name: "Add Chicken Shawarma" }));
    fireEvent.click(screen.getByRole("button", { name: "View cart" }));
    expect(screen.getByTestId("cart-sheet")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("+9715…"), {
      target: { value: "+971501234567" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Place order/i }));
    await waitFor(() =>
      expect(channelsApi.placePublicStoreOrder).toHaveBeenCalled(),
    );
    expect(await screen.findByText(/Order placed: R1-0009/)).toBeInTheDocument();
  });
});
