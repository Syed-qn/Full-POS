import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearStaffSession, setStaffSession } from "../lib/navAccess";
import { renderWithProviders } from "../test/render";
import { AppShell } from "./AppShell";

afterEach(() => {
  // @ts-expect-error test cleanup
  delete globalThis.window.posBridge;
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    value: true,
  });
  clearStaffSession();
  localStorage.clear();
  vi.restoreAllMocks();
});

function renderShell(connectionDown?: boolean) {
  return renderWithProviders(
    <AppShell connectionDown={connectionDown}>
      <div>child-content</div>
    </AppShell>,
  );
}

describe("AppShell offline wiring", () => {
  it("shows top-bar Offline badge from navigator offline", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: false,
    });
    renderShell();
    expect(screen.getByText("Offline")).toBeInTheDocument();
    expect(screen.getByText(/Live updates paused/i)).toBeInTheDocument();
    expect(screen.getByText("child-content")).toBeInTheDocument();
  });

  it("does not show Offline badge when online", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });
    renderShell();
    expect(screen.queryByText("Offline")).not.toBeInTheDocument();
    expect(screen.queryByText(/Live updates paused/i)).not.toBeInTheDocument();
  });

  it("respects connectionDown override when true while navigator online", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });
    renderShell(true);
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("respects connectionDown override when false while navigator offline", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: false,
    });
    renderShell(false);
    expect(screen.queryByText("Offline")).not.toBeInTheDocument();
  });
});

describe("AppShell role chrome", () => {
  it("hides sidebar for kitchen role", () => {
    setStaffSession({ role: "kitchen", name: "Cook" });
    renderShell();
    const shell = document.querySelector("[data-role-mode]");
    expect(shell).toHaveAttribute("data-role-mode", "kitchen");
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("shows sidebar for cashier role", () => {
    setStaffSession({ role: "cashier", name: "Cash" });
    renderShell();
    expect(document.querySelector("[data-role-mode]")).toHaveAttribute(
      "data-role-mode",
      "cashier",
    );
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });
});
