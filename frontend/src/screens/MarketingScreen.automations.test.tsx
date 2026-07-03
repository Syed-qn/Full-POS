import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MarketingScreen } from "./MarketingScreen";

const automations = [
  {
    preset_key: "welcome",
    title: "Welcome offer",
    description: "After first order.",
    enabled: false,
    template_id: null,
    segment_id: null,
    config: { delay_hours: 1 },
    stats: {},
    save_blocked: false,
  },
  {
    preset_key: "recurring",
    title: "Recurring promo",
    description: "Day 3 then weekly.",
    enabled: false,
    template_id: null,
    segment_id: null,
    config: { lead_minutes: 15 },
    stats: {},
    save_blocked: false,
  },
  {
    preset_key: "winback",
    title: "Win-back",
    description: "Lapsed customers.",
    enabled: false,
    template_id: null,
    segment_id: null,
    config: { lapsed_days: 60, cooldown_days: 60 },
    stats: {},
    save_blocked: false,
  },
  {
    preset_key: "reorder",
    title: "Reorder reminder",
    description: "Before usual order time.",
    enabled: false,
    template_id: null,
    segment_id: null,
    config: { lead_minutes: 15 },
    stats: {},
    save_blocked: false,
  },
];

describe("MarketingScreen automation tab", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date", "setInterval", "clearInterval"] });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((input: unknown, init?: RequestInit) => {
        const url = typeof input === "string" ? input : (input as Request).url;
        if (url.includes("/api/v1/me"))
          return Promise.resolve(
            new Response(JSON.stringify({ settings: {} }), { status: 200 }),
          );
        if (url.includes("/marketing/automations") && init?.method === "PATCH")
          return Promise.resolve(
            new Response(
              JSON.stringify({
                ...automations[0],
                enabled: true,
                template_id: 5,
                save_blocked: false,
              }),
              { status: 200 },
            ),
          );
        if (url.includes("/marketing/automations"))
          return Promise.resolve(
            new Response(JSON.stringify(automations), { status: 200 }),
          );
        if (url.includes("/marketing/templates"))
          return Promise.resolve(
            new Response(
              JSON.stringify([
                {
                  id: 5,
                  meta_template_name: "promo_welcome",
                  status: "approved",
                  body: "Hi {{1}}!",
                },
              ]),
              { status: 200 },
            ),
          );
        if (url.includes("/marketing/audience"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        if (url.includes("/marketing/segments"))
          return Promise.resolve(new Response("[]", { status: 200 }));
        return Promise.resolve(new Response("not found", { status: 404 }));
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders four automation cards", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /^automation$/i }));
    await waitFor(() =>
      expect(screen.getByText(/welcome offer/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/recurring promo/i)).toBeInTheDocument();
    expect(screen.getByText(/win-back/i)).toBeInTheDocument();
    expect(screen.getByText(/reorder reminder/i)).toBeInTheDocument();
  });

  it("PATCHes automation when template selected", async () => {
    render(<MarketingScreen />);
    await vi.advanceTimersByTimeAsync(0);
    fireEvent.click(screen.getByRole("button", { name: /^automation$/i }));
    await waitFor(() =>
      expect(screen.getByText("Welcome offer")).toBeInTheDocument(),
    );
    const tplBtn = screen
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("Welcome") && !b.textContent?.includes("offer"));
    expect(tplBtn).toBeTruthy();
    fireEvent.click(tplBtn!);
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() => {
      const patchCall = vi.mocked(fetch).mock.calls.find(
        ([u, init]) =>
          String(u).includes("/marketing/automations/welcome") &&
          init?.method === "PATCH",
      );
      expect(patchCall).toBeTruthy();
      const body = JSON.parse(String(patchCall?.[1]?.body)) as {
        template_id?: number;
      };
      expect(body.template_id).toBe(5);
    });
  });
});