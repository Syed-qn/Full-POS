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

describe("MarketingScreen broadcast audience", () => {
  let broadcastBody: Record<string, unknown> | null = null;

  beforeEach(() => {
    broadcastBody = null;
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: unknown, init?: RequestInit) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/marketing/broadcast") && init?.method === "POST") {
          broadcastBody = JSON.parse(String(init.body));
          return Promise.resolve(
            new Response(
              JSON.stringify({
                campaign_id: 1,
                queued: 1,
                suppressed_cap: 0,
                suppressed_optout: 0,
                suppressed_window: 0,
              }),
              { status: 201 },
            ),
          );
        }
        if (url.includes("/api/v1/me"))
          return Promise.resolve(
            new Response(JSON.stringify({ settings: {} }), { status: 200 }),
          );
        if (url.includes("/marketing/segments"))
          return Promise.resolve(
            new Response(
              JSON.stringify([
                {
                  id: 9,
                  name: "Biryani fans",
                  last_preview_count: 47,
                  plain_english: "fans",
                  updated_at: "2026-07-02T10:00:00Z",
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
              JSON.stringify([
                { key: "all", label: "All Customers", count: 100 },
                { key: "champions", label: "Champions", count: 12 },
              ]),
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

  it("selecting saved segment clears RFM and sends segment_id", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Biryani fans")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /biryani fans/i }));
    fireEvent.change(screen.getByLabelText(/optional coupon/i), {
      target: { value: "10" },
    });
    const sendBtn = screen.getByRole("button", { name: /send via whatsapp/i });
    fireEvent.click(sendBtn);
    fireEvent.click(sendBtn);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(broadcastBody).not.toBeNull());
    expect(broadcastBody).toMatchObject({
      template_id: 3,
      segment_id: 9,
      coupon_value: "10.00",
    });
    expect(broadcastBody).not.toHaveProperty("rfm_segment");
  });
});