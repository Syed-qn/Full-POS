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

  it("clears stored token and redirects to /login on 401", async () => {
    localStorage.setItem("ops_token", "tok-expired");
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/orders", assign });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "token expired" }), { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiClient.get("/api/v1/me")).rejects.toBeInstanceOf(ApiError);

    expect(localStorage.getItem("ops_token")).toBeNull();
    expect(assign).toHaveBeenCalledWith("/login");
  });

  it("does not redirect on 401 when already on /login (no loop)", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/login", assign });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "bad credentials" }), { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiClient.post("/api/v1/auth/login", {})).rejects.toBeInstanceOf(ApiError);

    expect(assign).not.toHaveBeenCalled();
  });
});

describe("apiClient inside Electron shell", () => {
  const originalWindow = globalThis.window;

  afterEach(() => {
    // @ts-expect-error test cleanup
    globalThis.window = originalWindow;
  });

  it("routes GET requests through window.posBridge when present", async () => {
    const posBridgeRequest = vi.fn().mockResolvedValue({
      status: 200,
      body: { id: 1, name: "Test Rider" },
    });
    // @ts-expect-error augmenting window for this test only
    globalThis.window.posBridge = { request: posBridgeRequest };

    const result = await apiClient.get("/api/v1/riders/1");

    expect(posBridgeRequest).toHaveBeenCalledWith("GET", "/api/v1/riders/1", undefined);
    expect(result).toEqual({ id: 1, name: "Test Rider" });
    // @ts-expect-error test cleanup
    delete globalThis.window.posBridge;
  });

  it("postForm bypasses the bridge (FormData can't cross Electron IPC) and uses plain fetch instead", async () => {
    const posBridgeRequest = vi.fn();
    // @ts-expect-error augmenting window for this test only
    globalThis.window.posBridge = { request: posBridgeRequest };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const form = new FormData();
    form.append("file", new Blob(["x"]), "dish.jpg");
    await apiClient.postForm("/api/v1/dishes/image", form);

    expect(posBridgeRequest).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalled();
    const [, init] = fetchMock.mock.calls[0];
    expect(init.body).toBe(form);
    // @ts-expect-error test cleanup
    delete globalThis.window.posBridge;
  });
});
