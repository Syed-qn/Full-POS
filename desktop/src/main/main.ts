import { app, BrowserWindow } from "electron";
import path from "path";
import { openLocalDb, initSchema } from "./db";
import { startSyncScheduler } from "./scheduler";

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
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
