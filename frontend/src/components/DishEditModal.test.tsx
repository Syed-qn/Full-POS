import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DishEditModal } from "./DishEditModal";

// Toaster pulls in app-level context we don't need here.
vi.mock("./Toaster", () => ({ toast: vi.fn() }));

describe("DishEditModal serving-size variants", () => {
  afterEach(() => vi.restoreAllMocks());

  it("adds variant rows and submits them in the create body", async () => {
    let posted: any = null;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          posted = JSON.parse(init.body as string);
          return Promise.resolve(new Response(JSON.stringify({ id: 9 }), { status: 201 }));
        }
        return Promise.resolve(new Response("{}", { status: 200 }));
      }),
    );

    render(
      <DishEditModal
        menuId={5}
        dish="new"
        categories={[]}
        nextNumber={300}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );

    await userEvent.type(screen.getByPlaceholderText("Chicken Biryani"), "Chicken Biryani");
    await userEvent.type(screen.getByPlaceholderText("20.00"), "18.00");

    await userEvent.click(screen.getByRole("button", { name: /add serving size/i }));
    await userEvent.type(screen.getByLabelText("Serving size 1 name"), "4 serve");
    await userEvent.type(screen.getByLabelText("Serving size 1 price"), "60");

    await userEvent.click(screen.getByRole("button", { name: "Add dish" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted.variants).toEqual([{ name: "4 serve", price_aed: "60" }]);
  });

  it("disables save while a variant row is partially filled", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("{}", { status: 200 }))));
    render(
      <DishEditModal
        menuId={5}
        dish="new"
        categories={[]}
        nextNumber={300}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    await userEvent.type(screen.getByPlaceholderText("Chicken Biryani"), "Biryani");
    await userEvent.type(screen.getByPlaceholderText("20.00"), "18.00");
    await userEvent.click(screen.getByRole("button", { name: /add serving size/i }));
    // Name typed, price left blank → save disabled.
    await userEvent.type(screen.getByLabelText("Serving size 1 name"), "4 serve");
    expect(screen.getByRole("button", { name: "Add dish" })).toBeDisabled();
  });

  it("blocks a serving size of 1 (single serve is the base price)", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("{}", { status: 200 }))));
    render(
      <DishEditModal
        menuId={5}
        dish="new"
        categories={[]}
        nextNumber={300}
        onClose={() => {}}
        onSaved={() => {}}
      />,
    );
    await userEvent.type(screen.getByPlaceholderText("Chicken Biryani"), "Biryani");
    await userEvent.type(screen.getByPlaceholderText("20.00"), "20");
    await userEvent.click(screen.getByRole("button", { name: /add serving size/i }));
    await userEvent.type(screen.getByLabelText("Serving size 1 name"), "1 serve");
    await userEvent.type(screen.getByLabelText("Serving size 1 price"), "20");
    expect(screen.getByRole("button", { name: "Add dish" })).toBeDisabled();
    expect(screen.getByText(/must be 2 or more/i)).toBeInTheDocument();
  });
});
