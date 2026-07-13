import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { LiveOpsScreen } from "./LiveOpsScreen";

const NOW = Date.parse("2026-06-06T10:00:00Z");

describe("LiveOpsScreen", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: NOW, toFake: ["Date", "setInterval", "clearInterval"] });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nf", { status: 404 })));
  });
  afterEach(() => vi.useRealTimers());

  it("shows the loading skeleton before the first poll resolves", () => {
    renderWithProviders(<LiveOpsScreen />);
    // data is still null on first paint → skeleton, not KPI values.
    expect(screen.getByLabelText("Loading live operations")).toBeInTheDocument();
    expect(screen.queryByText("Orders Today")).not.toBeInTheDocument();
  });

  it("renders KPI strip and the live feed from fixtures", async () => {
    renderWithProviders(<LiveOpsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Orders Today")).toBeInTheDocument());
    // Late/urgent orders appear on both the attention strip and the Late board lane.
    await waitFor(() => expect(screen.getAllByText("Ali Hassan").length).toBeGreaterThan(0));
    expect(screen.getByRole("toolbar", { name: /primary actions/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new order/i })).toBeInTheDocument();
  });

  it("shows urgent section for orders within 10 minutes of SLA", async () => {
    renderWithProviders(<LiveOpsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    // Order 47 has 32 min elapsed (8 remaining) → urgent
    await waitFor(() =>
      expect(screen.getByText(/needs attention now/i)).toBeInTheDocument()
    );
  });

  it("owner bottom bar includes Floor, Expo, Reports, Kitchen", async () => {
    renderWithProviders(<LiveOpsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Orders Today")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^floor$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^expo$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^reports$/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^kitchen$/i })).toBeInTheDocument();
  });
});
