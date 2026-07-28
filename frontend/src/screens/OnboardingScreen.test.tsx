import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The map and the Meta popup both reach outside the component (tiles, Facebook
// SDK). Stub them down to the one thing this screen cares about: the picked pin.
vi.mock("../components/LocationPickerModal", () => ({
  LocationPickerModal: ({ onSave }: { onSave: (lat: number, lng: number) => void }) => (
    <button type="button" onClick={() => onSave(25.2048, 55.2708)}>
      PICK DUBAI
    </button>
  ),
}));
vi.mock("../components/MetaConnectPanel", () => ({
  MetaConnectPanel: () => <div>META PANEL</div>,
}));

import { OnboardingScreen } from "./OnboardingScreen";

function renderScreen() {
  return render(
    <MemoryRouter initialEntries={["/onboarding"]}>
      <Routes>
        <Route path="/onboarding" element={<OnboardingScreen />} />
        <Route path="/" element={<div>DASHBOARD</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

/** /me answers with a fresh signup: named, but still at the 0.0/0.0 default. */
function stubApi(me: { name: string; lat: number; lng: number }) {
  const calls: { url: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.includes("/onboarding/status")) {
      return new Response(JSON.stringify({ complete: false, has_meta: false }), { status: 200 });
    }
    if (url.includes("/onboarding/complete")) {
      return new Response(JSON.stringify({ id: 1 }), { status: 200 });
    }
    return new Response(JSON.stringify({ id: 1, ...me }), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

describe("OnboardingScreen", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("is a single page — no step wizard", async () => {
    stubApi({ name: "La Cafe", lat: 0, lng: 0 });
    renderScreen();
    await screen.findByDisplayValue("La Cafe");
    expect(screen.queryByRole("list", { name: /onboarding steps/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^continue$/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /finish setup/i })).toBeInTheDocument();
  });

  it("refuses to finish while the restaurant is still at 0.0/0.0", async () => {
    const calls = stubApi({ name: "La Cafe", lat: 0, lng: 0 });
    renderScreen();
    await screen.findByDisplayValue("La Cafe");

    await userEvent.click(screen.getByRole("button", { name: /finish setup/i }));

    expect(await screen.findByText(/set your restaurant location/i)).toBeInTheDocument();
    // Nothing was saved and onboarding was not completed.
    expect(calls.some((c) => c.url.includes("/onboarding/complete"))).toBe(false);
    expect(screen.queryByText("DASHBOARD")).not.toBeInTheDocument();
  });

  it("saves the pin then completes, and lands on the dashboard", async () => {
    const calls = stubApi({ name: "La Cafe", lat: 0, lng: 0 });
    renderScreen();
    await screen.findByDisplayValue("La Cafe");

    await userEvent.click(screen.getByRole("button", { name: /set on map/i }));
    await userEvent.click(screen.getByRole("button", { name: /pick dubai/i }));
    await userEvent.click(screen.getByRole("button", { name: /finish setup/i }));

    await waitFor(() => expect(screen.getByText("DASHBOARD")).toBeInTheDocument());

    const patch = calls.find((c) => c.url.endsWith("/api/v1/me") && c.body);
    expect(patch?.body).toMatchObject({ name: "La Cafe", lat: 25.2048, lng: 55.2708 });
    // Order matters: completion is gated on the STORED location, so saving the
    // pin has to happen first or the server refuses.
    const patchAt = calls.findIndex((c) => c.url.endsWith("/api/v1/me") && c.body);
    const completeAt = calls.findIndex((c) => c.url.includes("/onboarding/complete"));
    expect(patchAt).toBeLessThan(completeAt);
  });

  it("finishes without WhatsApp — it is optional", async () => {
    const calls = stubApi({ name: "La Cafe", lat: 25.2048, lng: 55.2708 });
    renderScreen();
    await screen.findByDisplayValue("La Cafe");

    // Already located from /me, so WhatsApp is the only thing left undone.
    await userEvent.click(screen.getByRole("button", { name: /finish setup/i }));

    await waitFor(() => expect(screen.getByText("DASHBOARD")).toBeInTheDocument());
    expect(calls.some((c) => c.url.includes("/onboarding/complete"))).toBe(true);
  });

  it("requires a restaurant name", async () => {
    stubApi({ name: "", lat: 25.2048, lng: 55.2708 });
    renderScreen();
    await screen.findByRole("button", { name: /finish setup/i });

    await userEvent.click(screen.getByRole("button", { name: /finish setup/i }));
    expect(await screen.findByText(/restaurant name is required/i)).toBeInTheDocument();
  });
});
