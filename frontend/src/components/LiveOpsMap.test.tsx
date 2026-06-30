import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { LiveOpsMap } from "./LiveOpsMap";

vi.mock("leaflet", () => {
  const layer = { clearLayers: vi.fn(), addTo: vi.fn(() => layer), addLayer: vi.fn() };
  const map = {
    setView: vi.fn(() => map),
    remove: vi.fn(),
    invalidateSize: vi.fn(),
    fitBounds: vi.fn(),
  };
  const api = {
    map: vi.fn(() => map),
    tileLayer: vi.fn(() => ({ addTo: vi.fn() })),
    layerGroup: vi.fn(() => layer),
    circleMarker: vi.fn(() => ({ bindTooltip: vi.fn(() => ({ addTo: vi.fn() })) })),
    circle: vi.fn(() => ({ bindTooltip: vi.fn(() => ({ addTo: vi.fn() })) })),
    polyline: vi.fn(() => ({ bindTooltip: vi.fn(() => ({ addTo: vi.fn() })) })),
    latLngBounds: vi.fn(),
  };
  return { ...api, default: api };
});

vi.mock("../lib/dispatchApi", () => ({
  fetchLiveOpsMap: vi.fn(),
}));

import { fetchLiveOpsMap } from "../lib/dispatchApi";

describe("LiveOpsMap", () => {
  beforeEach(() => {
    vi.mocked(fetchLiveOpsMap).mockResolvedValue({
      origin: { lat: 25.2, lng: 55.2, name: "Test" },
      batches: [],
      sla_rings: [],
    });
  });

  it("renders fleet map with provided data", () => {
    render(
      <LiveOpsMap
        mapData={{
          origin: { lat: 25.2, lng: 55.2 },
          batches: [
            {
              batch_id: 1,
              rider_id: 2,
              status: "planned",
              color: "#0ea5e9",
              stops: [],
              polyline: [[25.2, 55.2], [25.21, 55.21]],
            },
          ],
          sla_rings: [
            {
              order_id: 9,
              order_number: "R1-9",
              lat: 25.21,
              lng: 55.21,
              sla_deadline: "2026-06-30T12:00:00Z",
              minutes_remaining: 12,
              urgency: "warn",
              radius_km: 1.2,
            },
          ],
        }}
      />,
    );
    expect(screen.getByLabelText(/live fleet map/i)).toBeInTheDocument();
    expect(screen.getByText(/SLA warn/i)).toBeInTheDocument();
  });
});