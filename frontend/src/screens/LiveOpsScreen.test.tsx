import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveOpsScreen } from "./LiveOpsScreen";

const NOW = Date.parse("2026-06-06T10:00:00Z");

describe("LiveOpsScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date", "setInterval", "clearInterval"] });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nf", { status: 404 })));
  });
  afterEach(() => vi.useRealTimers());

  it("shows the loading skeleton before the first poll resolves", () => {
    render(
      <MemoryRouter>
        <LiveOpsScreen />
      </MemoryRouter>,
    );
    // data is still null on first paint → skeleton, not KPI values.
    expect(screen.getByLabelText("Loading live operations")).toBeInTheDocument();
    expect(screen.queryByText("Orders Today")).not.toBeInTheDocument();
  });

  it("renders KPI strip and the live feed from fixtures", async () => {
    render(
      <MemoryRouter>
        <LiveOpsScreen />
      </MemoryRouter>,
    );
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Orders Today")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Ali Hassan")).toBeInTheDocument());
  });

  it("shows urgent section for orders within 10 minutes of SLA", async () => {
    render(
      <MemoryRouter>
        <LiveOpsScreen />
      </MemoryRouter>,
    );
    await vi.advanceTimersByTimeAsync(0);
    // Order 47 has 32 min elapsed (8 remaining) → urgent
    await waitFor(() =>
      expect(screen.getByText(/needs attention now/i)).toBeInTheDocument()
    );
  });
});
