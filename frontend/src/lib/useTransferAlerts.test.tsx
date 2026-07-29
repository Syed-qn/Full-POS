import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { needsMyAction, useTransferAlerts } from "./useTransferAlerts";
import type { BranchTransferOut } from "./types";

const toasts = vi.hoisted(() => ({ messages: [] as string[] }));
vi.mock("../components/Toaster", () => ({
  toast: (message: string) => toasts.messages.push(message),
}));

const live = vi.hoisted(() => ({ listeners: [] as Array<(e: unknown) => void> }));
vi.mock("./liveEvents", () => ({
  subscribeLive: (fn: (e: unknown) => void) => {
    live.listeners.push(fn);
    return () => {
      const i = live.listeners.indexOf(fn);
      if (i >= 0) live.listeners.splice(i, 1);
    };
  },
}));

const api = vi.hoisted(() => ({ transfers: [] as unknown[] }));
vi.mock("./branchTransfersApi", () => ({
  listBranchTransfers: () => Promise.resolve(api.transfers),
}));

const role = vi.hoisted(() => ({ value: null as string | null }));
vi.mock("./navAccess", () => ({
  getSessionRole: () => role.value,
}));

function transfer(over: Partial<BranchTransferOut> = {}): BranchTransferOut {
  return {
    id: 7,
    status: "pending",
    direction: "out",
    from_restaurant_id: 1,
    from_branch_name: "Marina",
    to_restaurant_id: 2,
    to_branch_name: "Deira",
    dispatched_by: null,
    received_by: null,
    note: null,
    created_at: "2026-07-29T07:00:00",
    lines: [
      {
        ingredient_name: "Rice",
        unit: "kg",
        qty_requested: "2.000",
        quantity: "2.000",
        qty_received: null,
      },
    ],
    ...over,
  } as BranchTransferOut;
}

describe("useTransferAlerts", () => {
  beforeEach(() => {
    toasts.messages.length = 0;
    live.listeners.length = 0;
    localStorage.clear();
    // null is the owner's restaurant token — no role claim on it.
    role.value = null;
    api.transfers = [];
  });

  it("alerts once for a request, and never again for the same one", async () => {
    api.transfers = [transfer()];
    const first = renderHook(() => useTransferAlerts());
    await waitFor(() => expect(toasts.messages).toHaveLength(1));
    expect(toasts.messages[0]).toContain("Deira asked for Rice 2.000 kg");

    // A live event fires on every transfer write for BOTH branches, so the
    // same request would otherwise re-toast on any unrelated stock change.
    for (const fn of [...live.listeners]) fn({ topic: "inventory" });
    await waitFor(() => expect(first.result.current).toHaveLength(1));
    expect(toasts.messages).toHaveLength(1);

    // ...and a reload must not replay it either.
    first.unmount();
    renderHook(() => useTransferAlerts());
    await waitFor(() => expect(live.listeners.length).toBeGreaterThan(0));
    expect(toasts.messages).toHaveLength(1);
  });

  it("still lists the request after the toast is spent", async () => {
    api.transfers = [transfer()];
    const { result } = renderHook(() => useTransferAlerts());
    // The toast is a moment; the alert center is the standing record. Losing
    // the row once it has been announced is how a request gets forgotten.
    await waitFor(() => expect(result.current).toHaveLength(1));
    expect(result.current[0].id).toBe("transfer-7");
    expect(result.current[0].level).toBe("warning");
  });

  it("batches several into one toast", async () => {
    api.transfers = [transfer({ id: 1 }), transfer({ id: 2 }), transfer({ id: 3 })];
    renderHook(() => useTransferAlerts());
    // Three toasts for three requests is the duplicate problem wearing a
    // different hat.
    await waitFor(() => expect(toasts.messages).toHaveLength(1));
    expect(toasts.messages[0]).toContain("3 branch transfers need you");
  });

  it("says nothing to a cashier", async () => {
    role.value = "cashier";
    api.transfers = [transfer()];
    const { result } = renderHook(() => useTransferAlerts());
    // They cannot even reach the endpoint — it 403s — so an alert would be
    // noise about something they cannot act on.
    await waitFor(() => expect(result.current).toHaveLength(0));
    expect(toasts.messages).toHaveLength(0);
  });

  it("ignores transfers that are waiting on the OTHER branch", () => {
    const mine = transfer({ id: 1, status: "pending", direction: "out" });
    const theirs = transfer({ id: 2, status: "pending", direction: "in" });
    const arriving = transfer({ id: 3, status: "in_transit", direction: "in" });
    const sent = transfer({ id: 4, status: "in_transit", direction: "out" });
    const done = transfer({ id: 5, status: "completed", direction: "in" });

    // Only the two you can actually act on: a request aimed at you, and a
    // delivery only you can confirm.
    expect(needsMyAction([mine, theirs, arriving, sent, done]).map((t) => t.id)).toEqual([
      1, 3,
    ]);
  });
});
