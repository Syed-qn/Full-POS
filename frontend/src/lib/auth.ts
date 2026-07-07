import { apiClient } from "./apiClient";
import { clearCachedOnboardingComplete } from "./onboardingGate";
import type { TokenOut } from "./types";

const TOKEN_KEY = apiClient.TOKEN_KEY;

function desktopBridge(): { setAuthToken: (token: string | null) => void } | undefined {
  return (window as unknown as { posBridge?: { setAuthToken: (token: string | null) => void } })
    .posBridge;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

// SECURITY: migrate to httpOnly cookie + CSRF when backend supports it
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  desktopBridge()?.setAuthToken(token);
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
  clearCachedOnboardingComplete();
  desktopBridge()?.setAuthToken(null);
}

/** Call once at app boot (inside the Electron shell) so a token already stored from a
 * previous session reaches the main process, which starts fresh with no token every
 * launch — without this, a user who's already logged in stays logged in on the web
 * (localStorage persists) but every bridged API call would run unauthenticated. */
export function syncAuthTokenToDesktopShell(): void {
  const bridge = desktopBridge();
  if (!bridge) return;
  const token = getToken();
  if (token) bridge.setAuthToken(token);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

export async function login(email: string, password: string): Promise<void> {
  const res = await apiClient.post<TokenOut>("/api/v1/auth/login", { email, password });
  setToken(res.access_token);
}

export async function signup(
  name: string,
  email: string,
  password: string,
): Promise<void> {
  await apiClient.post("/api/v1/auth/signup", {
    name,
    email,
    password,
  });
  await login(email, password);
}
