import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SideDrawer } from "./SideDrawer";

describe("SideDrawer", () => {
  it("renders children when open", () => {
    render(
      <SideDrawer open title="Order #047" onClose={() => {}}>
        <p>Detail body</p>
      </SideDrawer>,
    );
    expect(screen.getByText("Detail body")).toBeInTheDocument();
    expect(screen.getByText("Order #047")).toBeInTheDocument();
  });

  it("does not render content when closed", () => {
    render(
      <SideDrawer open={false} title="X" onClose={() => {}}>
        <p>Hidden</p>
      </SideDrawer>,
    );
    expect(screen.queryByText("Hidden")).not.toBeInTheDocument();
  });

  it("calls onClose on scrim click", async () => {
    const onClose = vi.fn();
    render(
      <SideDrawer open title="X" onClose={onClose}>
        <p>Body</p>
      </SideDrawer>,
    );
    await userEvent.click(screen.getByTestId("drawer-scrim"));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
