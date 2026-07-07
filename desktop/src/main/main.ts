import { app, BrowserWindow } from "electron";
import path from "path";

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
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
