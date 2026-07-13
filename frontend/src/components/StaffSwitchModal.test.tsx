import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearStaffSession, getStaffSession } from "../lib/navAccess";
import { StaffSwitchModal } from "./StaffSwitchModal";

describe("StaffSwitchModal", () => {
  beforeEach(() => {
    localStorage.clear();
    clearStaffSession();
    Object.defineProperty(navigator, "onLine", { configurable: true, value: true });
  });
  afterEach(() => vi.restoreAllMocks());

  it("does not render when closed", () => {
    render(
      <MemoryRouter>
        <StaffSwitchModal open={false} onClose={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("staff-switch-modal")).not.toBeInTheDocument();
  });

  it("switches staff via PIN and stores session + token", async () => {
    const onClose = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            access_token: "staff-jwt",
            token_type: "bearer",
            role: "kitchen",
            staff_id: 9,
            name: "Chef Ali",
            training_mode: false,
          }),
          { status: 200 },
        ),
      ),
    );

    render(
      <MemoryRouter>
        <StaffSwitchModal open onClose={onClose} navigateToHome={false} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/staff id/i), "9");
    await userEvent.click(screen.getByRole("button", { name: "Digit 1" }));
    await userEvent.click(screen.getByRole("button", { name: "Digit 2" }));
    await userEvent.click(screen.getByRole("button", { name: "Digit 3" }));
    await userEvent.click(screen.getByRole("button", { name: "Digit 4" }));
    await userEvent.click(screen.getByTestId("staff-switch-submit"));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(localStorage.getItem("ops_token")).toBe("staff-jwt");
    expect(getStaffSession()?.role).toBe("kitchen");
    expect(getStaffSession()?.name).toBe("Chef Ali");
  });

  it("shows error on invalid PIN", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Invalid PIN" }), { status: 401 }),
      ),
    );

    render(
      <MemoryRouter>
        <StaffSwitchModal open onClose={() => {}} />
      </MemoryRouter>,
    );

    await userEvent.type(screen.getByLabelText(/staff id/i), "3");
    for (const d of ["1", "2", "3", "4"]) {
      await userEvent.click(screen.getByRole("button", { name: `Digit ${d}` }));
    }
    await userEvent.click(screen.getByTestId("staff-switch-submit"));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/invalid pin/i));
  });
});
