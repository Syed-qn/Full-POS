import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getToken, login, logout, setToken, syncAuthTokenToDesktopShell } from "./auth";

describe("auth store", () => {
  beforeEach(() => localStorage.clear());

  it("stores and reads token", () => {
    setToken("abc");
    expect(getToken()).toBe("abc");
  });

  it("logout clears token", () => {
    setToken("abc");
    logout();
    expect(getToken()).toBeNull();
  });

  it("logout drops the cached restaurant name so the next account is not mislabelled", async () => {
    // Reproduces a real report: switch to a branch, sign out, sign back in as
    // the owner, and the chrome still read the BRANCH name. The name lives in a
    // module-level cache that only dies on a full page load, and signing out is
    // a client-side route change.
    const { useRestaurantName } = await import("./brand");
    const { renderHook, waitFor } = await import("@testing-library/react");

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ name: "La Cafe 2" }), { status: 200 }),
      ),
    );
    setToken("branch-token");
    const first = renderHook(() => useRestaurantName());
    await waitFor(() => expect(first.result.current).toBe("La Cafe 2"));

    logout();

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ name: "La Cafe" }), { status: 200 }),
      ),
    );
    setToken("owner-token");
    const second = renderHook(() => useRestaurantName());
    await waitFor(() => expect(second.result.current).toBe("La Cafe"));
  });

  it("login posts credentials and persists token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ access_token: "jwt-xyz", token_type: "bearer" }), {
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await login("+97150000000", "password1");
    expect(getToken()).toBe("jwt-xyz");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/auth/login");
  });
});

describe("auth <-> desktop shell bridge sync", () => {
  afterEach(() => {
    // @ts-expect-error test cleanup
    delete globalThis.window.posBridge;
  });

  it("pushes the token to posBridge on setToken when running in the shell", () => {
    const setAuthToken = vi.fn();
    // @ts-expect-error augment window for test
    globalThis.window.posBridge = { setAuthToken };

    setToken("shell-tok");

    expect(setAuthToken).toHaveBeenCalledWith("shell-tok");
  });

  it("pushes null to posBridge on logout when running in the shell", () => {
    const setAuthToken = vi.fn();
    // @ts-expect-error augment window for test
    globalThis.window.posBridge = { setAuthToken };

    setToken("shell-tok");
    logout();

    expect(setAuthToken).toHaveBeenLastCalledWith(null);
  });

  it("does nothing when not running in the shell (no posBridge)", () => {
    // no window.posBridge set — must not throw
    expect(() => setToken("web-tok")).not.toThrow();
  });

  it("syncAuthTokenToDesktopShell pushes the current stored token on boot", () => {
    const setAuthToken = vi.fn();
    localStorage.setItem("ops_token", "boot-tok");
    // @ts-expect-error augment window for test
    globalThis.window.posBridge = { setAuthToken };

    syncAuthTokenToDesktopShell();

    expect(setAuthToken).toHaveBeenCalledWith("boot-tok");
  });
});
