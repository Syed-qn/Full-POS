import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketingScreen } from "./MarketingScreen";

describe("MarketingScreen campaigns tab", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: unknown) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/api/v1/me"))
          return Promise.resolve(
            new Response(JSON.stringify({ settings: {} }), { status: 200 }),
          );
        if (url.includes("/marketing/campaigns"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        if (url.includes("/marketing/templates"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        if (url.includes("/marketing/audience"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        return Promise.resolve(new Response("not found", { status: 404 }));
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows campaigns empty state when no campaigns returned", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /^campaigns$/i }));
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByText(/no campaigns yet/i)).toBeInTheDocument(),
    );
  });

  it("renders campaign table rows when campaigns are returned", async () => {
    const campaigns = [
      {
        id: 7,
        type: "promotional",
        status: "sent",
        stats: { sent: 50, delivered: 48, converted: 5, rfm_segment: "champions" },
        created_at: "2026-07-01T10:00:00Z",
        template_name: "promo_weekend_deal",
        audience_label: "Champions",
        template_id: 1,
        segment_id: null,
      },
    ];
    vi.mocked(fetch).mockImplementation((input: unknown) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/marketing/campaigns"))
        return Promise.resolve(new Response(JSON.stringify(campaigns), { status: 200 }));
      if (url.includes("/api/v1/me"))
        return Promise.resolve(
          new Response(JSON.stringify({ settings: {} }), { status: 200 }),
        );
      if (url.includes("/marketing/templates"))
        return Promise.resolve(new Response("[]", { status: 200 }));
      if (url.includes("/marketing/audience"))
        return Promise.resolve(new Response("[]", { status: 200 }));
      return Promise.resolve(new Response("not found", { status: 404 }));
    });
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /^campaigns$/i }));
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("Champions")).toBeInTheDocument());
    const row = screen.getByRole("row", { name: /champions/i });
    expect(row).toHaveTextContent("Weekend Deal");
    expect(row).toHaveTextContent("48");
    expect(row).toHaveTextContent("5");
  });

  it("opens drawer with stats when a campaign row is clicked", async () => {
    const campaigns = [
      {
        id: 9,
        type: "promotional",
        status: "sent",
        stats: { sent: 10, suppressed_optout: 2 },
        created_at: "2026-07-02T12:00:00Z",
        template_name: "promo_lunch",
        audience_label: "All Customers",
        template_id: null,
        segment_id: null,
      },
    ];
    vi.mocked(fetch).mockImplementation((input: unknown) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/marketing/campaigns/9/stats"))
        return Promise.resolve(
          new Response(
            JSON.stringify({
              sent: 10,
              delivered: 9,
              converted: 2,
              suppressed_optout: 2,
              suppressed_cap: 1,
              suppressed_window: 0,
            }),
            { status: 200 },
          ),
        );
      if (url.includes("/marketing/campaigns"))
        return Promise.resolve(new Response(JSON.stringify(campaigns), { status: 200 }));
      if (url.includes("/api/v1/me"))
        return Promise.resolve(
          new Response(JSON.stringify({ settings: {} }), { status: 200 }),
        );
      if (url.includes("/marketing/templates"))
        return Promise.resolve(new Response("[]", { status: 200 }));
      if (url.includes("/marketing/audience"))
        return Promise.resolve(new Response("[]", { status: 200 }));
      return Promise.resolve(new Response("not found", { status: 404 }));
    });
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /^campaigns$/i }));
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => expect(screen.getByText("All Customers")).toBeInTheDocument());
    fireEvent.click(screen.getByText("All Customers"));
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /campaign #9/i })).toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByText("Conversion rate")).toBeInTheDocument());
    expect(screen.getByText("Opt-out")).toBeInTheDocument();
  });
});