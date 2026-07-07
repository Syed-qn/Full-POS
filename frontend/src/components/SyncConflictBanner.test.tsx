import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { SyncConflictBanner } from "./SyncConflictBanner";

afterEach(() => {
  // @ts-expect-error test cleanup
  delete globalThis.window.posBridge;
});

describe("SyncConflictBanner", () => {
  it("shows nothing when there are no conflicts", async () => {
    // @ts-expect-error augment window for test
    globalThis.window.posBridge = {
      listConflicts: vi.fn().mockResolvedValue([]),
    };
    render(<SyncConflictBanner />);
    expect(await screen.findByTestId("sync-conflict-banner")).toHaveTextContent("");
  });

  it("shows a count when conflicts exist", async () => {
    // @ts-expect-error augment window for test
    globalThis.window.posBridge = {
      listConflicts: vi.fn().mockResolvedValue([
        { id: "a", entity: "orders", path: "/api/v1/orders/8/status" },
      ]),
    };
    render(<SyncConflictBanner />);
    expect(
      await screen.findByText(/1 change couldn't sync/i),
    ).toBeInTheDocument();
  });
});
