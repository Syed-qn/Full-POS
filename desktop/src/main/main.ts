import { app, BrowserWindow, ipcMain } from "electron";
import path from "path";
import { openLocalDb, initSchema } from "./db";
import { startSyncScheduler } from "./scheduler";
import { enqueueOp } from "./pendingOps";

export function createMainWindow(loadUrl: string): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.loadURL(loadUrl);
  return win;
}

// Real app bootstrap — not exercised by the unit test (mocked `app`/`BrowserWindow`).
if (require.main === module) {
  app.whenReady().then(() => {
    const target =
      process.env.POS_SHELL_URL ??
      `file://${path.join(process.resourcesPath, "frontend", "dist", "index.html")}`;
    createMainWindow(target);

    const db = openLocalDb(path.join(app.getPath("userData"), "pos-cache.sqlite"));
    initSchema(db);
    startSyncScheduler(
      db,
      process.env.POS_API_BASE ?? "https://api.fullpos.example",
      fetch,
      () => process.env.POS_AUTH_TOKEN ?? "", // replaced by real auth-token storage in Task 10
      15000,
    );

    ipcMain.handle(
      "pos-api-request",
      async (_event, { method, path: reqPath, body }: { method: string; path: string; body: unknown }) => {
        const apiBase = process.env.POS_API_BASE ?? "https://api.fullpos.example";
        const token = process.env.POS_AUTH_TOKEN ?? "";
        try {
          const resp = await fetch(new URL(reqPath, apiBase).toString(), {
            method,
            headers: {
              Authorization: `Bearer ${token}`,
              ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
            },
            body: body !== undefined ? JSON.stringify(body) : undefined,
          });
          const responseBody = resp.status === 204 ? undefined : await resp.json();
          return { status: resp.status, body: responseBody };
        } catch {
          // Offline: queue mutating requests, let GETs fail (renderer already has a
          // local cache read-through added in Task 11's conflict/cache-read step).
          if (method !== "GET") {
            enqueueOp(db, {
              entity: reqPath.split("/")[3] ?? "unknown",
              entityId: null,
              op: method === "POST" ? "create" : "update",
              method,
              path: reqPath,
              payload: body,
            });
            return { status: 202, body: { queued: true } };
          }
          return { status: 503, body: { detail: "offline, no cache available" } };
        }
      },
    );

    ipcMain.handle("pos-list-conflicts", () => {
      return db
        .prepare(`SELECT id, entity, path FROM pending_ops WHERE status = 'conflict'`)
        .all();
    });
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
