import type Database from "better-sqlite3";
import { pullSync, pushSync } from "./sync";

export function startSyncScheduler(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  getToken: () => string,
  intervalMs: number,
): { stop(): void } {
  const timer = setInterval(async () => {
    const token = getToken();
    await pushSync(db, apiBase, fetchImpl, token);
    await pullSync(db, apiBase, fetchImpl, token);
  }, intervalMs);
  return {
    stop() {
      clearInterval(timer);
    },
  };
}
