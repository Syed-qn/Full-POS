import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppInviteModal } from "./AppInviteModal";
import type { RiderOut } from "../lib/types";

const RIDER: RiderOut = {
  id: 7,
  name: "Imran",
  phone: "+971500000010",
  status: "available",
} as RiderOut;

describe("AppInviteModal", () => {
  it("shows the restaurant number and the 'send hi first' instruction", () => {
    render(
      <AppInviteModal rider={RIDER} restaurantPhone="+918754568384" onClose={() => {}} />,
    );
    expect(screen.getByText(/Send app link to Imran/i)).toBeInTheDocument();
    expect(screen.getByText("+918754568384")).toBeInTheDocument();
    expect(screen.getByText(/after the rider contacts you first/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm & send link/i })).toBeInTheDocument();
  });

  it("falls back to generic wording when the restaurant number is unknown", () => {
    render(<AppInviteModal rider={RIDER} restaurantPhone={null} onClose={() => {}} />);
    expect(screen.getByText(/your WhatsApp business number/i)).toBeInTheDocument();
  });

  it("Cancel closes the dialog without sending", () => {
    const onClose = vi.fn();
    render(
      <AppInviteModal rider={RIDER} restaurantPhone="+918754568384" onClose={onClose} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
