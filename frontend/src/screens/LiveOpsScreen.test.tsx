import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveOpsScreen } from "./LiveOpsScreen";

const NOW = Date.parse("2026-06-06T10:00:00Z");

describe("LiveOpsScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date", "setInterval", "clearInterval"] });
    // 404 → ordersApi fixture fallback (orders 47/48/49)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nf", { status: 404 })));
  });
  afterEach(() => vi.useRealTimers());

  it("renders KPI strip and the live feed from fixtures", async () => {
    render(
      <MemoryRouter>
        <LiveOpsScreen />
      </MemoryRouter>,
    );
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Orders Today")).toBeInTheDocument());
    // fixture order 47 customer in feed
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
  });

  it("routes order 47 (32 min elapsed) into the yellow SLA lane", async () => {
    render(
      <MemoryRouter>
        <LiveOpsScreen />
      </MemoryRouter>,
    );
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      const yellow = screen.getByTestId("sla-lane-yellow");
      expect(yellow.textContent).toContain("#47");
    });
  });
});
