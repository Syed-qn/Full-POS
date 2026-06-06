import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RiderCard } from "./RiderCard";
import type { RiderOut } from "../lib/types";

const rider: RiderOut = { id: 3, name: "Ali Hassan", phone: "+9715", status: "on_delivery" };

describe("RiderCard", () => {
  it("renders name and status label", () => {
    render(<RiderCard rider={rider} onStatusChange={() => {}} />);
    expect(screen.getByText("Ali Hassan")).toBeInTheDocument();
    expect(screen.getByText(/On Delivery/i)).toBeInTheDocument();
  });

  it("deactivate action triggers status change", async () => {
    const onStatusChange = vi.fn();
    render(<RiderCard rider={rider} onStatusChange={onStatusChange} />);
    await userEvent.click(screen.getByRole("button", { name: /deactivate/i }));
    expect(onStatusChange).toHaveBeenCalledWith(3, "deactivated");
  });

  it("shows stale-location border when stale", () => {
    render(<RiderCard rider={rider} onStatusChange={() => {}} stale />);
    expect(screen.getByTestId("rider-card").className).toContain("stale");
  });
});
