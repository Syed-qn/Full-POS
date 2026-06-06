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
  it("renders number, name, price", () => {
    render(<DishCard dish={dish} onToggle={() => {}} />);
    expect(screen.getByText("#110")).toBeInTheDocument();
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
});
