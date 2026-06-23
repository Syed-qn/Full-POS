import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RiderCard } from "./RiderCard";
import type { RiderOut } from "../lib/types";

const rider: RiderOut = {
  id: 3,
  name: "Ali Hassan",
  phone: "+9715",
  status: "on_delivery",
  delivered_24h: 4,
  delivered_lifetime: 152,
  last_lat: null,
  last_lng: null,
  last_location_at: null,
};

describe("RiderCard", () => {
  it("renders name and status label", () => {
    render(<RiderCard rider={rider} onStatusChange={() => {}} onDelete={() => {}} />);
    expect(screen.getByText("Ali Hassan")).toBeInTheDocument();
    expect(screen.getByText(/On Delivery/i)).toBeInTheDocument();
  });

  it("deactivate action triggers status change", async () => {
    const onStatusChange = vi.fn();
    render(<RiderCard rider={rider} onStatusChange={onStatusChange} onDelete={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: /deactivate/i }));
    expect(onStatusChange).toHaveBeenCalledWith(3, "deactivated");
  });

  it("shows last-24h and lifetime delivery counts", () => {
    render(<RiderCard rider={rider} onStatusChange={() => {}} onDelete={() => {}} />);
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("152")).toBeInTheDocument();
    expect(screen.getByText(/last 24 hrs/i)).toBeInTheDocument();
  });

  it("shows 'no location' and hides the map button when never shared", () => {
    render(<RiderCard rider={rider} onStatusChange={() => {}} onDelete={() => {}} />);
    expect(screen.getByText(/no location shared yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /view on map/i })).not.toBeInTheDocument();
  });

  it("shows a live freshness label + map button when a recent ping exists", () => {
    const recent = new Date(Date.now() - 60_000).toISOString();
    const located: RiderOut = {
      ...rider,
      last_lat: 25.2,
      last_lng: 55.27,
      last_location_at: recent,
    };
    render(<RiderCard rider={located} onStatusChange={() => {}} onDelete={() => {}} />);
    expect(screen.getByText(/live · seen/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /view on map/i })).toBeInTheDocument();
  });

  it("shows stale-location border when stale", () => {
    render(<RiderCard rider={rider} onStatusChange={() => {}} onDelete={() => {}} stale />);
    expect(screen.getByTestId("rider-card").className).toContain("stale");
  });
});
