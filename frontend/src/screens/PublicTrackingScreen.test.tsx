import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as trackingApi from "../lib/trackingApi";
import { PublicTrackingScreen } from "./PublicTrackingScreen";

vi.mock("../lib/trackingApi", async (importOriginal) => {
  const actual = await importOriginal<typeof trackingApi>();
  return {
    ...actual,
    fetchPublicTracking: vi.fn(),
    fetchPublicTrackingLocation: vi.fn(),
  };
});

function renderTrack() {
  return render(
    <MemoryRouter initialEntries={["/track/tok-1"]}>
      <Routes>
        <Route path="/track/:trackingToken" element={<PublicTrackingScreen />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PublicTrackingScreen", () => {
  beforeEach(() => {
    vi.mocked(trackingApi.fetchPublicTracking).mockReset();
    vi.mocked(trackingApi.fetchPublicTrackingLocation).mockReset();
  });

  it("shows status timeline and hides map while food is preparing", async () => {
    vi.mocked(trackingApi.fetchPublicTracking).mockResolvedValue({
      orderId: 1,
      orderNumber: "R1-0001",
      status: "preparing",
      trackingUrl: "/track/tok-1",
      lastUpdatedAt: null,
      location: null,
      restaurant: { latitude: 25.2, longitude: 55.2, label: "Demo Cafe" },
      destination: null,
    });
    // Transient location miss (not terminal 404/410) — keep timeline active, no map yet.
    vi.mocked(trackingApi.fetchPublicTrackingLocation).mockRejectedValue(
      new Error("no location yet"),
    );

    renderTrack();
    expect(await screen.findByTestId("status-timeline")).toBeInTheDocument();
    expect(screen.getByTestId("status-hero")).toHaveTextContent(/preparing/i);
    expect(screen.getByTestId("map-placeholder")).toBeInTheDocument();
    expect(screen.queryByTestId("tracking-map")).not.toBeInTheDocument();
    // No kitchen internals
    expect(screen.queryByText(/KDS|ticket|station/i)).not.toBeInTheDocument();
  });

  it("shows map once rider is en route", async () => {
    vi.mocked(trackingApi.fetchPublicTracking).mockResolvedValue({
      orderId: 1,
      orderNumber: "R1-0001",
      status: "picked_up",
      trackingUrl: "/track/tok-1",
      lastUpdatedAt: "2026-07-09T10:00:00Z",
      location: {
        latitude: 25.21,
        longitude: 55.27,
        updatedAt: "2026-07-09T10:00:00Z",
        status: "picked_up",
      },
      restaurant: { latitude: 25.2, longitude: 55.2, label: "Demo Cafe" },
      destination: { latitude: 25.22, longitude: 55.28, label: "Home" },
    });
    vi.mocked(trackingApi.fetchPublicTrackingLocation).mockResolvedValue({
      latitude: 25.21,
      longitude: 55.27,
      updatedAt: "2026-07-09T10:00:00Z",
      status: "picked_up",
    });

    renderTrack();
    await waitFor(() => expect(screen.getByTestId("tracking-map")).toBeInTheDocument());
    expect(screen.getByTestId("status-hero")).toHaveTextContent(/on the way/i);
  });
});
