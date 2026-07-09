import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AlertCenter } from "./AlertCenter";

describe("AlertCenter a11y", () => {
  it("autofocuses the close control on open", async () => {
    render(<AlertCenter alerts={[]} onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /close alerts/i })).toHaveFocus();
    });
  });

  it("Escape invokes onClose", () => {
    const onClose = vi.fn();
    render(
      <AlertCenter
        alerts={[{ id: "1", level: "warning", title: "Late order" }]}
        onClose={onClose}
      />,
    );
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("is a modal dialog with accessible name", () => {
    render(<AlertCenter alerts={[]} onClose={() => {}} />);
    const dialog = screen.getByRole("dialog", { name: /alert center/i });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("id", "alert-center-panel");
  });
});
