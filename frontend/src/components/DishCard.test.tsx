import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DishCard } from "./DishCard";
import type { DishOut } from "../lib/types";

const dish: DishOut = {
  id: 1, dish_number: 110, name: "Chicken Biryani", price_aed: "22.00",
  category: "Rice", description: null, is_available: true,
};

describe("DishCard", () => {
  it("renders name and price (dish number is hidden from the UI)", () => {
    render(<DishCard dish={dish} onToggle={() => {}} />);
    expect(screen.queryByText("#110")).not.toBeInTheDocument();
    expect(screen.getByText("Chicken Biryani")).toBeInTheDocument();
    expect(screen.getByText("AED 22.00")).toBeInTheDocument();
  });

  it("calls onToggle with negated availability", async () => {
    const onToggle = vi.fn();
    render(<DishCard dish={dish} onToggle={onToggle} />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onToggle).toHaveBeenCalledWith(1, false);
  });

  it("flags extraction error when number or price missing", () => {
    render(<DishCard dish={{ ...dish, dish_number: null }} onToggle={() => {}} />);
    expect(screen.getByTestId("dish-card").className).toContain("error");
  });

  it("shows an Edit button for a normal dish when onEdit is provided", () => {
    render(<DishCard dish={dish} onToggle={() => {}} onEdit={() => {}} />);
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.queryByText("From POS")).not.toBeInTheDocument();
  });

  it("locks edit AND delete for a POS-synced dish (shows From POS)", async () => {
    const onEdit = vi.fn();
    const onDelete = vi.fn();
    const posDish: DishOut = { ...dish, pos_product_id: "19680" };
    render(
      <DishCard dish={posDish} onToggle={() => {}} onEdit={onEdit} onDelete={onDelete} />
    );
    // Neither Edit nor Delete; a clear "From POS" tag instead.
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
    expect(screen.getByText("From POS")).toBeInTheDocument();
    // Clicking the card must NOT open the editor either.
    await userEvent.click(screen.getByText("Chicken Biryani"));
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("POS lock leaves the availability toggle working", async () => {
    const onToggle = vi.fn();
    const posDish: DishOut = { ...dish, pos_product_id: "19680" };
    render(<DishCard dish={posDish} onToggle={onToggle} onEdit={() => {}} />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onToggle).toHaveBeenCalledWith(1, false);
  });

  it("shows a price range when the dish has serving-size variants", () => {
    const withVariants: DishOut = {
      ...dish,
      variants: [
        { name: "1 serve", price_aed: "18", dish_number: null },
        { name: "4 serve", price_aed: "60", dish_number: null },
      ],
    };
    render(<DishCard dish={withVariants} onToggle={() => {}} />);
    expect(screen.getByText("AED 18 to 60")).toBeInTheDocument();
  });
});
