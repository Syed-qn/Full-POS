import type Database from "better-sqlite3";

interface DishPayload {
  id: number;
  updated_at: string;
  [key: string]: unknown;
}

function getCursor(db: Database.Database, entity: string): string | null {
  const row = db
    .prepare(`SELECT last_cursor FROM sync_state WHERE entity = ?`)
    .get(entity) as { last_cursor: string } | undefined;
  return row?.last_cursor ?? null;
}

function setCursor(db: Database.Database, entity: string, cursor: string): void {
  db.prepare(
    `INSERT INTO sync_state (entity, last_synced_at, last_cursor)
     VALUES (@entity, @now, @cursor)
     ON CONFLICT(entity) DO UPDATE SET last_synced_at = @now, last_cursor = @cursor`,
  ).run({ entity, now: new Date().toISOString(), cursor });
}

export async function pullSync(
  db: Database.Database,
  apiBase: string,
  fetchImpl: typeof fetch,
  token: string,
): Promise<void> {
  const cursor = getCursor(db, "menu");
  const url = new URL("/api/v1/menu/dishes", apiBase);
  if (cursor) url.searchParams.set("updated_since", cursor);

  const resp = await fetchImpl(url.toString(), {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!resp.ok) return; // offline or server error — leave cache as-is, retried next tick

  const dishes = (await resp.json()) as DishPayload[];
  const upsert = db.prepare(
    `INSERT INTO local_menu (dish_id, payload, updated_at)
     VALUES (@dish_id, @payload, @updated_at)
     ON CONFLICT(dish_id) DO UPDATE SET payload = @payload, updated_at = @updated_at`,
  );
  let maxUpdatedAt = cursor;
  const tx = db.transaction((rows: DishPayload[]) => {
    for (const dish of rows) {
      upsert.run({
        dish_id: dish.id,
        payload: JSON.stringify(dish),
        updated_at: dish.updated_at,
      });
      if (!maxUpdatedAt || dish.updated_at > maxUpdatedAt) {
        maxUpdatedAt = dish.updated_at;
      }
    }
  });
  tx(dishes);

  if (maxUpdatedAt) setCursor(db, "menu", maxUpdatedAt);
}
