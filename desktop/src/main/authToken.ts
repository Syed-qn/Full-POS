import fs from "fs";

let cachedToken = "";
let persistPath: string | null = null;

/** Call once at app boot with a real file path (e.g. under app.getPath("userData"))
 * so a token set via setAuthToken survives an app restart. */
export function initAuthTokenStore(filePath: string): void {
  persistPath = filePath;
  try {
    cachedToken = fs.readFileSync(filePath, "utf8").trim();
  } catch {
    cachedToken = ""; // no file yet — not logged in, or first launch
  }
}

export function getAuthToken(): string {
  return cachedToken;
}

export function setAuthToken(token: string): void {
  cachedToken = token;
  if (persistPath) {
    try {
      fs.writeFileSync(persistPath, token, "utf8");
    } catch {
      // best-effort persistence; the in-memory token still works this session
    }
  }
}
