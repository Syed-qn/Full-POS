import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("posBridge", {
  request: (method: string, path: string, body: unknown) =>
    ipcRenderer.invoke("pos-api-request", { method, path, body }),
  listConflicts: () => ipcRenderer.invoke("pos-list-conflicts"),
});
