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

  it("renders KPI strip and the order board from fixtures", async () => {
    renderWithProviders(<LiveOpsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Orders Today")).toBeInTheDocument());
    // Orders land on the board table.
    await waitFor(() => expect(screen.getAllByText("Ali Hassan").length).toBeGreaterThan(0));
    // The WhatsApp channel tile + board tab are present alongside Dine In / Take Away.
    expect(screen.getByTestId("kpi-whatsapp")).toBeInTheDocument();
    expect(screen.getByTestId("board-tab-whatsapp")).toBeInTheDocument();
  });

  it("flags an order past its SLA on the board", async () => {
    renderWithProviders(<LiveOpsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    // Order 47 is within/past its SLA window → LATE/OVERDUE chip on its row.
    await waitFor(() =>
      expect(screen.getAllByText(/late|overdue/i).length).toBeGreaterThan(0)
    );
  });

  it("offers channel board tabs including WhatsApp", async () => {
    renderWithProviders(<LiveOpsScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Orders Today")).toBeInTheDocument());
    expect(screen.getByTestId("board-tab-all")).toBeInTheDocument();
    expect(screen.getByTestId("board-tab-dine")).toBeInTheDocument();
    expect(screen.getByTestId("board-tab-takeaway")).toBeInTheDocument();
    expect(screen.getByTestId("board-tab-whatsapp")).toBeInTheDocument();
  });
});
