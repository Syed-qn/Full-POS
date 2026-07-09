import { app, BrowserWindow, ipcMain } from "electron";
import { autoUpdater } from "electron-updater";
import path from "path";
import { openLocalDb, initSchema } from "./db";
import { startSyncScheduler } from "./scheduler";
import { enqueueOp } from "./pendingOps";
import { initAuthTokenStore, getAuthToken, setAuthToken } from "./authToken";
import { initAutoUpdater } from "./updater";
import { pollAndPrint } from "./printJobPoller";
import { FailoverPrinter, FileSpoolPrinter, NotImplementedPrinter } from "./native/printer";
import {
  flushLocalPrintJobsAsync,
  getNetworkState,
  listCachedMenu,
  listLocalOrders,
  queueLocalPrint,
  queueOfflinePayment,
  resolveConflict,
  saveLocalOrder,
  setNetworkOnline,
} from "./offlineStore";

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

    const userData = app.getPath("userData");
    const db = openLocalDb(path.join(userData, "pos-cache.sqlite"));
    initSchema(db);
    initAuthTokenStore(path.join(userData, "auth-token.txt"));

    const apiBase = process.env.POS_API_BASE ?? "https://api.fullpos.example";
    startSyncScheduler(db, apiBase, fetch, getAuthToken, 15000);

    // Primary may be unimplemented hardware; FileSpool is always available offline.
    const spoolDir = path.join(userData, "print-spool");
    const printer = new FailoverPrinter(
      new NotImplementedPrinter(),
      new FileSpoolPrinter(spoolDir),
    );
    setInterval(() => {
      pollAndPrint(apiBase, fetch, getAuthToken(), printer).catch(() => {
        // never let a poll failure kill the interval — retried next tick
      });
      void flushLocalPrintJobsAsync(db, printer);
    }, 10000);

    ipcMain.handle("pos-set-auth-token", (_event, token: string | null) => {
      setAuthToken(token ?? "");
    });

    ipcMain.handle(
      "pos-api-request",
      async (_event, { method, path: reqPath, body }: { method: string; path: string; body: unknown }) => {
        const base = process.env.POS_API_BASE ?? "https://api.fullpos.example";
        const token = getAuthToken();
        try {
          const resp = await fetch(new URL(reqPath, base).toString(), {
            method,
            headers: {
              Authorization: `Bearer ${token}`,
              ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
            },
            body: body !== undefined ? JSON.stringify(body) : undefined,
          });
          setNetworkOnline(db, true);
          const responseBody = resp.status === 204 ? undefined : await resp.json();
          // cache successful order/menu GETs
          if (method === "GET" && resp.ok && Array.isArray(responseBody)) {
            if (reqPath.includes("/menu/dishes")) {
              for (const dish of responseBody as Array<{ id: number; updated_at: string }>) {
                db.prepare(
                  `INSERT INTO local_menu (dish_id, payload, updated_at)
                   VALUES (@dish_id, @payload, @updated_at)
                   ON CONFLICT(dish_id) DO UPDATE SET payload = @payload, updated_at = @updated_at`,
                ).run({
                  dish_id: dish.id,
                  payload: JSON.stringify(dish),
                  updated_at: dish.updated_at || new Date().toISOString(),
                });
              }
            }
            if (reqPath.includes("/orders") && !reqPath.includes("/orders/")) {
              for (const order of responseBody as Array<{ id: number }>) {
                saveLocalOrder(db, order, false);
              }
            }
          }
          return { status: resp.status, body: responseBody };
        } catch (e) {
          setNetworkOnline(db, false, e instanceof Error ? e.message : "offline");
          // Offline: queue mutating requests; serve cache for GETs.
          if (method !== "GET") {
            // Offline order create → local_orders + pending_ops
            if (method === "POST" && reqPath.includes("/orders")) {
              const localId = saveLocalOrder(
                db,
                { ...(body as object), status: "draft", offline: true },
                true,
              );
              // KOT offline print
              queueLocalPrint(
                db,
                "kot",
                `OFFLINE KOT\nOrder local#${localId}\n${JSON.stringify(body)}`,
              );
              void flushLocalPrintJobsAsync(db, printer);
            }
            if (method === "POST" && reqPath.includes("/payments")) {
              const payBody = body as {
                amount_aed?: string;
                tender_type?: string;
                order_id?: number;
              };
              queueOfflinePayment(db, {
                amount_aed: payBody.amount_aed || "0",
                tender_type: payBody.tender_type || "cash",
                order_id: payBody.order_id,
              });
              queueLocalPrint(
                db,
                "receipt",
                `OFFLINE RECEIPT\n${JSON.stringify(body)}`,
              );
              void flushLocalPrintJobsAsync(db, printer);
            }
            enqueueOp(db, {
              entity: reqPath.split("/")[3] ?? "unknown",
              entityId: null,
              op: method === "POST" ? "create" : "update",
              method,
              path: reqPath,
              payload: body,
            });
            return { status: 202, body: { queued: true, offline: true } };
          }
          // GET cache read-through
          if (reqPath.includes("/menu/dishes")) {
            return { status: 200, body: listCachedMenu(db) };
          }
          if (reqPath.includes("/orders") && !reqPath.match(/\/orders\/\d+/)) {
            return { status: 200, body: listLocalOrders(db) };
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

    ipcMain.handle(
      "pos-resolve-conflict",
      (_event, { id, action }: { id: string; action: "retry" | "discard" }) => {
        resolveConflict(db, id, action);
        return { ok: true };
      },
    );

    ipcMain.handle("pos-network-status", () => getNetworkState(db));

    ipcMain.handle("pos-list-pending-ops", () => {
      return db
        .prepare(
          `SELECT id, entity, path, status, attempts, created_at FROM pending_ops
           WHERE status IN ('pending','failed','conflict') ORDER BY created_at`,
        )
        .all();
    });

    ipcMain.handle(
      "pos-offline-print",
      async (_event, { kind, payload }: { kind: "kot" | "receipt"; payload: string }) => {
        const id = queueLocalPrint(db, kind, payload);
        await flushLocalPrintJobsAsync(db, printer);
        return { id };
      },
    );

    initAutoUpdater(autoUpdater);
  });
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}
