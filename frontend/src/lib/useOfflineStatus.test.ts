import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readNavigatorOnline, useOfflineStatus } from "./useOfflineStatus";

afterEach(() => {
  // @ts-expect-error test cleanup
  delete globalThis.window.posBridge;
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    value: true,
  });
  vi.restoreAllMocks();
});

describe("readNavigatorOnline", () => {
  it("returns true when navigator.onLine is true", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });
    expect(readNavigatorOnline()).toBe(true);
  });

  it("returns false when navigator.onLine is false", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: false,
    });
    expect(readNavigatorOnline()).toBe(false);
  });
});

describe("useOfflineStatus", () => {
  it("reports online when navigator is online", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });
    const { result } = renderHook(() => useOfflineStatus(60_000));
    expect(result.current.online).toBe(true);
    expect(result.current.offline).toBe(false);
    expect(result.current.pendingCount).toBe(0);
    expect(result.current.isDesktop).toBe(false);
  });

  it("reports offline when navigator is offline", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: false,
    });
    const { result } = renderHook(() => useOfflineStatus(60_000));
    expect(result.current.online).toBe(false);
    expect(result.current.offline).toBe(true);
  });

  it("reacts to window online/offline events", () => {
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });
    const { result } = renderHook(() => useOfflineStatus(60_000));
    expect(result.current.offline).toBe(false);

    act(() => {
      Object.defineProperty(navigator, "onLine", {
        configurable: true,
        value: false,
      });
      window.dispatchEvent(new Event("offline"));
    });
    expect(result.current.offline).toBe(true);

    act(() => {
      Object.defineProperty(navigator, "onLine", {
        configurable: true,
        value: true,
      });
      window.dispatchEvent(new Event("online"));
    });
    expect(result.current.offline).toBe(false);
  });

  it("merges desktop bridge networkStatus and pending ops", async () => {
    // @ts-expect-error augment window for test
    globalThis.window.posBridge = {
      networkStatus: vi.fn().mockResolvedValue({ online: false, last_error: "down" }),
      listPendingOps: vi
        .fn()
        .mockResolvedValue([{ id: "1", status: "pending", path: "/api/v1/orders" }]),
    };

    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });

    const { result } = renderHook(() => useOfflineStatus(60_000));

    await waitFor(() => {
      expect(result.current.isDesktop).toBe(true);
      expect(result.current.offline).toBe(true);
      expect(result.current.pendingCount).toBe(1);
      expect(result.current.hasPending).toBe(true);
    });
  });

  it("stays online when desktop bridge reports online", async () => {
    // @ts-expect-error augment window for test
    globalThis.window.posBridge = {
      networkStatus: vi.fn().mockResolvedValue({ online: true, last_error: null }),
      listPendingOps: vi.fn().mockResolvedValue([]),
    };

    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      value: true,
    });

    const { result } = renderHook(() => useOfflineStatus(60_000));

    await waitFor(() => {
      expect(result.current.isDesktop).toBe(true);
      expect(result.current.online).toBe(true);
      expect(result.current.pendingCount).toBe(0);
    });
  });
});
