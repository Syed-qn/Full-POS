import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { recordManagerApproval, useManagerPinGate } from "./requireManagerPin";
import * as staffApi from "./staffApi";

vi.mock("./staffApi", () => ({
  submitManagerPin: vi.fn().mockResolvedValue({ id: 1, action_type: "void", status: "approved" }),
}));

function Harness({
  onDone,
}: {
  onDone: (ctx: { pin: string; reason: string }) => Promise<void>;
}) {
  const { requestPin, pinGate } = useManagerPinGate();
  return (
    <div>
      <button
        type="button"
        onClick={() =>
          requestPin({
            actionType: "void",
            actionLabel: "Void order",
            recordLabel: "ORD-9",
            reasonRequired: true,
            orderId: 9,
            confirmTitle: "Void this order?",
            confirmMessage: "Requires manager PIN.",
            execute: onDone,
          })
        }
      >
        Start void
      </button>
      {pinGate}
    </div>
  );
}

describe("requireManagerPin", () => {
  beforeEach(() => {
    vi.mocked(staffApi.submitManagerPin).mockClear();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("recordManagerApproval posts to staff approvals", async () => {
    await recordManagerApproval({
      pin: "1234",
      reason: "test",
      actionType: "refund",
      orderId: 3,
      amountAed: "5.00",
    });
    expect(staffApi.submitManagerPin).toHaveBeenCalledWith({
      pin: "1234",
      action_type: "refund",
      order_id: 3,
      amount_aed: "5.00",
      reason: "test",
    });
  });

  it("gates action behind ConfirmDialog then ApprovalPinModal", async () => {
    const execute = vi.fn().mockResolvedValue(undefined);
    render(<Harness onDone={execute} />);

    fireEvent.click(screen.getByRole("button", { name: /start void/i }));
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText(/requires manager pin/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /continue to pin/i }));
    expect(await screen.findByRole("dialog", { name: /manager approval/i })).toBeInTheDocument();
    expect(screen.getByText(/void order/i)).toBeInTheDocument();
    expect(screen.getByText("ORD-9")).toBeInTheDocument();

    for (const d of ["1", "2", "3", "4"]) {
      fireEvent.click(screen.getByRole("button", { name: `Digit ${d}` }));
    }
    fireEvent.change(screen.getByPlaceholderText(/why is this needed/i), {
      target: { value: "Customer no-show" },
    });
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));

    await waitFor(() => {
      expect(staffApi.submitManagerPin).toHaveBeenCalled();
      expect(execute).toHaveBeenCalledWith({ pin: "1234", reason: "Customer no-show" });
    });
  });
});
