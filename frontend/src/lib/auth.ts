import { apiClient } from "./apiClient";
import type { TokenOut } from "./types";

const TOKEN_KEY = apiClient.TOKEN_KEY;

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

// SECURITY: migrate to httpOnly cookie + CSRF when backend supports it
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

export async function login(phone: string, password: string): Promise<void> {
  const res = await apiClient.post<TokenOut>("/api/v1/auth/login", { phone, password });
  setToken(res.access_token);
}

export async function signup(
  name: string,
  phone: string,
  password: string,
): Promise<void> {
  await apiClient.post("/api/v1/auth/signup", {
    name,
    phone,
    password,
    lat: 25.2048,
    lng: 55.2708,
  });
  await login(phone, password);
}
