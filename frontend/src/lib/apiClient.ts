const API_BASE = import.meta.env.VITE_API_BASE ?? "";
export const TOKEN_KEY = "ops_token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  isForm = false,
): Promise<T> {
  const bridge = (globalThis as typeof globalThis & {
    window?: { posBridge?: { request: (m: string, p: string, b: unknown) => Promise<{ status: number; body: unknown }> } };
  }).window?.posBridge;

  // FormData/File can't cross Electron's IPC structured-clone boundary — fall through
  // to plain fetch even inside the shell (the renderer can still reach the real
  // backend directly over HTTPS; only mutating-queue/idempotency coverage is lost
  // for uploads, which is acceptable since binary uploads aren't part of the
  // offline write queue's scope).
  if (bridge && !isForm) {
    const { status, body: responseBody } = await bridge.request(method, path, body);
    if (status >= 400) {
      const detail =
        typeof (responseBody as { detail?: unknown })?.detail === "string"
          ? (responseBody as { detail: string }).detail
          : JSON.stringify(responseBody);
      throw new ApiError(status, detail);
    }
    return responseBody as T;
  }

  const headers: Record<string, string> = { ...authHeaders() };
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    if (isForm) {
      payload = body as FormData;
    } else {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
  }
  const resp = await fetch(`${API_BASE}${path}`, { method, headers, body: payload });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const data = await resp.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* non-JSON error body */
    }
    if (resp.status === 401) {
      // Session expired/invalid → drop the stored token and bounce to login.
      // Cleared directly (not via auth.logout) to avoid a circular import; guard
      // against a redirect loop when the failing request is the login page itself.
      localStorage.removeItem(TOKEN_KEY);
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const apiClient = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
  postForm: <T>(path: string, form: FormData) => request<T>("POST", path, form, true),
  TOKEN_KEY,
};
