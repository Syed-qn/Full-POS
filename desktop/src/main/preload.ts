import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("posBridge", {
  request: (method: string, path: string, body: unknown) =>
    ipcRenderer.invoke("pos-api-request", { method, path, body }),
  listConflicts: () => ipcRenderer.invoke("pos-list-conflicts"),
  resolveConflict: (id: string, action: "retry" | "discard") =>
    ipcRenderer.invoke("pos-resolve-conflict", { id, action }),
  networkStatus: () => ipcRenderer.invoke("pos-network-status"),
  listPendingOps: () => ipcRenderer.invoke("pos-list-pending-ops"),
  offlinePrint: (kind: "kot" | "receipt", payload: string) =>
    ipcRenderer.invoke("pos-offline-print", { kind, payload }),
  setAuthToken: (token: string | null) => ipcRenderer.invoke("pos-set-auth-token", token),
});
