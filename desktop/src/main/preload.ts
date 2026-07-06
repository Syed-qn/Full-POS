// Populated in Task 4 with the posBridge IPC surface. Empty context-isolated
// bridge for now so contextIsolation:true doesn't break window creation.
import { contextBridge } from "electron";

contextBridge.exposeInMainWorld("posBridge", {});
