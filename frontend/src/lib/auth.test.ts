import { beforeEach, describe, expect, it, vi } from "vitest";
import { getToken, login, logout, setToken } from "./auth";

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
