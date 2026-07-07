interface AutoUpdaterLike {
  checkForUpdatesAndNotify(): unknown;
  on(event: "error", listener: (error: Error) => void): unknown;
}

/**
 * Wires electron-updater's built-in "check, download, notify" flow. The feed
 * (where restaurants' installed .exes look for new releases) is configured in
 * electron-builder.yml's `publish` block, which reads POS_UPDATE_URL at build
 * time — set that env var once a real update host (S3/generic HTTP/GitHub
 * Releases) is chosen; until then this runs against no configured feed and
 * checkForUpdatesAndNotify() no-ops (electron-updater logs and does nothing
 * rather than throwing when no publish config is present).
 */
export function initAutoUpdater(autoUpdater: AutoUpdaterLike): void {
  autoUpdater.on("error", (error) => {
    // A failed update check must never crash a restaurant's running POS —
    // log and keep going; the next scheduled check tries again.
    console.error("auto-update check failed:", error);
  });
  autoUpdater.checkForUpdatesAndNotify();
}
