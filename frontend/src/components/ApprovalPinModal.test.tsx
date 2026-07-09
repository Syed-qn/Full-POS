import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApprovalPinModal } from "./ApprovalPinModal";

describe("ApprovalPinModal", () => {
  it("requires pin length before approve", async () => {
    const onApprove = vi.fn();
    render(
      <ApprovalPinModal
        open
        actionLabel="Void order"
        recordLabel="ORD-1"
        onCancel={() => {}}
        onApprove={onApprove}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(await screen.findByText(/at least 4 digits/i)).toBeInTheDocument();
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("submits pin from number pad", async () => {
    const onApprove = vi.fn().mockResolvedValue(undefined);
    render(
      <ApprovalPinModal
        open
        actionLabel="Refund"
        onCancel={() => {}}
        onApprove={onApprove}
      />,
    );

    for (const d of ["1", "2", "3", "4"]) {
      fireEvent.click(screen.getByRole("button", { name: `Digit ${d}` }));
    }
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));
    await waitFor(() => {
      expect(onApprove).toHaveBeenCalledWith({ pin: "1234", reason: "" });
    });
  });

  it("focuses first PIN pad control on open", async () => {
    render(
      <ApprovalPinModal open actionLabel="Void" onCancel={() => {}} onApprove={vi.fn()} />,
    );
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Digit 1" })).toHaveFocus();
    });
  });

  it("focuses reason field when reason is required", async () => {
    render(
      <ApprovalPinModal
        open
        actionLabel="Refund"
        reasonRequired
        onCancel={() => {}}
        onApprove={vi.fn()}
      />,
    );
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/why is this needed/i)).toHaveFocus();
    });
  });

  it("Escape closes the modal", () => {
    const onCancel = vi.fn();
    render(
      <ApprovalPinModal open actionLabel="Void" onCancel={onCancel} onApprove={vi.fn()} />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("exposes dialog aria-modal and labelled title", () => {
    render(
      <ApprovalPinModal open actionLabel="Discount" onCancel={() => {}} onApprove={vi.fn()} />,
    );
    const dialog = screen.getByRole("dialog", { name: /manager approval/i });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("button", { name: "Clear PIN" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Backspace" })).toBeInTheDocument();
  });
});
