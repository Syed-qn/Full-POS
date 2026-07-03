import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketingScreen } from "./MarketingScreen";

const approvedTemplate = {
  id: 3,
  meta_template_name: "promo_live",
  status: "approved",
  body: "Hi {{1}}, deal!",
  footer: "Reply STOP to opt out",
};

describe("MarketingScreen schedule broadcast", () => {
  let broadcastBody: Record<string, unknown> | null = null;

  beforeEach(() => {
    broadcastBody = null;
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.setSystemTime(new Date("2026-07-02T08:00:00Z"));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: unknown, init?: RequestInit) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/marketing/broadcast") && init?.method === "POST") {
          broadcastBody = JSON.parse(String(init.body));
          return Promise.resolve(
            new Response(
              JSON.stringify({
                campaign_id: 12,
                scheduled_at: broadcastBody?.scheduled_at,
                status: "scheduled",
              }),
              { status: 201 },
            ),
          );
        }
        if (url.includes("/marketing/campaigns") && init?.method === "DELETE") {
          return Promise.resolve(new Response(null, { status: 204 }));
        }
        if (url.includes("/api/v1/me"))
          return Promise.resolve(
            new Response(JSON.stringify({ settings: {} }), { status: 200 }),
          );
        if (url.includes("/marketing/campaigns") && (!init?.method || init.method === "GET"))
          return Promise.resolve(
            new Response(
              JSON.stringify([
                {
                  id: 12,
                  type: "promotional",
                  status: "scheduled",
                  stats: {},
                  scheduled_at: "2026-07-02T14:00:00.000Z",
                  template_name: "promo_live",
                  audience_label: "All Customers",
                  template_id: 3,
                },
              ]),
              { status: 200 },
            ),
          );
        if (url.includes("/marketing/templates"))
          return Promise.resolve(
            new Response(JSON.stringify([approvedTemplate]), { status: 200 }),
          );
        if (url.includes("/marketing/audience"))
          return Promise.resolve(
            new Response(
              JSON.stringify([{ key: "all", label: "All Customers", count: 5 }]),
              { status: 200 },
            ),
          );
        return Promise.resolve(new Response("not found", { status: 404 }));
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("schedule mode sends scheduled_at UTC", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /^schedule$/i }));
    const dateInput = document.querySelector('input[type="date"]') as HTMLInputElement;
    const timeInput = document.querySelector('input[type="time"]') as HTMLInputElement;
    fireEvent.change(dateInput, { target: { value: "2026-07-02" } });
    fireEvent.change(timeInput, { target: { value: "18:00" } });
    const sendBtn = screen.getByRole("button", { name: /schedule broadcast/i });
    fireEvent.click(sendBtn);
    fireEvent.click(sendBtn);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(broadcastBody).not.toBeNull());
    expect(broadcastBody?.scheduled_at).toBe("2026-07-02T14:00:00.000Z");
  });

  it("campaigns tab shows scheduled row and cancel action", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /^campaigns$/i }));
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText(/scheduled/i)).toBeInTheDocument());
    vi.stubGlobal("confirm", vi.fn(() => true));
    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));
    await vi.advanceTimersByTimeAsync(0);
  });
});