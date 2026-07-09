import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OfflineLimitsBanner } from "./OfflineLimitsBanner";

afterEach(() => {
  // @ts-expect-error test cleanup
  delete globalThis.window.posBridge;
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    value: true,
  });
  vi.restoreAllMocks();
});

function renderBanner(
  surface: Parameters<typeof OfflineLimitsBanner>[0]["surface"],
  forceOffline?: boolean,
) {
  return render(
    <MemoryRouter>
      <OfflineLimitsBanner surface={surface} forceOffline={forceOffline} />
    </MemoryRouter>,
  );
}

describe("OfflineLimitsBanner", () => {
  it("renders nothing when online", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });
    renderBanner("orders");
    expect(screen.queryByTestId("offline-limits-banner")).not.toBeInTheDocument();
  });

  it("shows works / blocked limits when offline (new-order)", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: false,
    });
    renderBanner("new-order");
    const banner = screen.getByTestId("offline-limits-banner");
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveAttribute("data-surface", "new-order");
    expect(screen.getByText(/Limited operations/i)).toBeInTheDocument();
    expect(screen.getByText(/Customer lookup/i)).toBeInTheDocument();
    expect(screen.getByText(/Still works/i)).toBeInTheDocument();
    expect(screen.getByText(/Blocked until online/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Reliability/i })).toHaveAttribute(
      "href",
      "/reliability",
    );
  });

  it("supports forceOffline for tests regardless of navigator", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });
    renderBanner("kds", true);
    expect(screen.getByTestId("offline-limits-banner")).toHaveAttribute(
      "data-surface",
      "kds",
    );
    expect(screen.getByText(/Ticket refresh/i)).toBeInTheDocument();
  });

  it("lists payments-specific blocked actions", () => {
    renderBanner("payments", true);
    expect(screen.getByText(/Till charge to cloud/i)).toBeInTheDocument();
    expect(screen.getByText(/Reconciliation/i)).toBeInTheDocument();
  });
});
