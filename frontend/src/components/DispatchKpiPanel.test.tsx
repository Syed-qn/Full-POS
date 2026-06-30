import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DispatchKpiPanel } from "./DispatchKpiPanel";
import { MOCK_DISPATCH_KPIS } from "../test/fixtures/dispatch";

vi.mock("../lib/dispatchApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/dispatchApi")>();
  return {
    ...actual,
    fetchDispatchKpis: vi.fn(),
  };
});

import { fetchDispatchKpis } from "../lib/dispatchApi";

describe("DispatchKpiPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchDispatchKpis).mockResolvedValue(MOCK_DISPATCH_KPIS);
  });

  it("renders batch rate, avg stops, and engine fallback from API", async () => {
    render(<DispatchKpiPanel />);
    await waitFor(() => expect(screen.getByText("42%")).toBeInTheDocument());
    expect(screen.getByText("2.1")).toBeInTheDocument();
    expect(screen.getByText("8%")).toBeInTheDocument();
    expect(screen.getByText(/batch rate/i)).toBeInTheDocument();
    expect(screen.getByText(/avg stops/i)).toBeInTheDocument();
    expect(screen.getByText(/engine fallback/i)).toBeInTheDocument();
  });

  it("renders provided KPI props without fetching", async () => {
    render(
      <DispatchKpiPanel
        kpis={{
          batch_rate_pct: 55,
          avg_stops: 2.8,
          engine_fallback_pct: 3,
        }}
      />,
    );
    expect(screen.getByText("55%")).toBeInTheDocument();
    expect(screen.getByText("2.8")).toBeInTheDocument();
    expect(screen.getByText("3%")).toBeInTheDocument();
    expect(fetchDispatchKpis).not.toHaveBeenCalled();
  });
});