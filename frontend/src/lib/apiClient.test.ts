import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiClient } from "./apiClient";

describe("apiClient", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it("injects bearer token from localStorage", async () => {
    localStorage.setItem("ops_token", "tok-123");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiClient.get("/api/v1/me");

    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok-123");
  });

  it("omits Authorization when no token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("{}", { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await apiClient.get("/api/v1/health");
    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("throws ApiError with status and detail on non-2xx", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "bad credentials" }), { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiClient.post("/api/v1/auth/login", {})).rejects.toMatchObject({
      status: 401,
      detail: "bad credentials",
    });
    await expect(apiClient.post("/api/v1/auth/login", {})).rejects.toBeInstanceOf(ApiError);
  });
});
