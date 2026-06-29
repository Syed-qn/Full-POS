import { useCallback, useEffect, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import { apiClient } from "../lib/apiClient";
import { syncCatalog } from "../lib/catalogApi";
import type { RestaurantOut } from "../lib/types";
import { fetchUnifiedMenu, syncCatalogFull, type UnifiedMenu } from "../lib/unifiedMenuApi";
import s from "./UnifiedMenuPanel.module.css";

const BADGE: Record<string, { label: string; cls: string }> = {
  linked: { label: "Linked", cls: s.linked },
  dish_only: { label: "Text only", cls: s.dishOnly },
  catalog_only: { label: "Meta only", cls: s.catOnly },
};

export function UnifiedMenuPanel({
  onCatalogIdSaved,
}: {
  onCatalogIdSaved?: () => void;
}) {
  const [menu, setMenu] = useState<UnifiedMenu | null>(null);
  const [catalogId, setCatalogId] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [savingId, setSavingId] = useState(false);

  const load = useCallback(async () => {
    try {
      const [unified, me] = await Promise.all([
        fetchUnifiedMenu(),
        apiClient.get<RestaurantOut>("/api/v1/me"),
      ]);
      setMenu(unified);
      const cid = ((me.settings as Record<string, unknown>)?.catalog_id as string) || "";
      setCatalogId(cid);
    } catch {
      /* keep last */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function saveCatalogId() {
    setSavingId(true);
    try {
      await apiClient.patch("/api/v1/settings", { catalog_id: catalogId.trim() });
      toast("Catalog ID saved");
      onCatalogIdSaved?.();
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't save catalog ID", "error");
    } finally {
      setSavingId(false);
    }
  }

  async function doSyncFull() {
    setSyncing(true);
    try {
      const res = await syncCatalogFull();
      toast(
        `Synced · ${res.total_active} in Meta` +
          (res.pushed ? ` · ${res.pushed} pushed` : "") +
          (res.linked ? ` · ${res.linked} linked` : ""),
      );
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Sync failed", "error");
    } finally {
      setSyncing(false);
    }
  }

  async function doPullOnly() {
    setSyncing(true);
    try {
      const res = await syncCatalog();
      toast(`Pulled ${res.total_active} products from Meta`);
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Pull failed", "error");
    } finally {
      setSyncing(false);
    }
  }

  if (loading) return <p className={s.empty}>Loading unified menu…</p>;

  return (
    <div className={s.panel}>
      <div className={s.head}>
        <div>
          <h3 className={s.title}>Unified menu</h3>
          <p className={s.sub}>
            One menu for ops and WhatsApp. Customers get catalogue cards when synced;
            text dishes and Meta products stay linked here.
          </p>
        </div>
        <div className={s.actions}>
          <Button variant="ghost" onClick={doPullOnly} disabled={syncing || !catalogId.trim()}>
            Pull from Meta
          </Button>
          <Button onClick={doSyncFull} disabled={syncing || !catalogId.trim()}>
            {syncing ? "Syncing…" : "Sync both ways"}
          </Button>
        </div>
      </div>

      <label className={s.catalogField}>
        <span className="label-upper">Meta Catalog ID</span>
        <input
          value={catalogId}
          onChange={(e) => setCatalogId(e.target.value)}
          placeholder="From Meta Commerce Manager"
        />
        <Button variant="ghost" onClick={saveCatalogId} disabled={savingId}>
          {savingId ? "Saving…" : "Save catalog ID"}
        </Button>
      </label>

      {menu ? (
        <div className={s.stats}>
          <span className={s.stat}>{menu.items.length} items</span>
          <span className={s.stat}>{menu.linked_count} linked</span>
          <span className={s.stat}>{menu.dish_only_count} text-only</span>
          <span className={s.stat}>{menu.catalog_only_count} Meta-only</span>
        </div>
      ) : null}

      {!menu || menu.items.length === 0 ? (
        <p className={s.empty}>
          Upload a menu, set your Catalog ID, then run <b>Sync both ways</b>.
        </p>
      ) : (
        <div className={s.grid}>
          {menu.items.map((item) => {
            const b = BADGE[item.link_status] ?? BADGE.dish_only;
            const key = `${item.link_status}-${item.dish_id ?? item.catalog_product_id}-${item.retailer_id}`;
            return (
              <div key={key} className={s.card}>
                {item.image_url ? (
                  <img className={s.thumb} src={item.image_url} alt={item.name} />
                ) : (
                  <div className={s.thumbPh}>🍽️</div>
                )}
                <div className={s.body}>
                  <div className={s.nameRow}>
                    <span className={s.name}>
                      {item.dish_number != null ? `${item.dish_number}. ` : ""}
                      {item.name}
                    </span>
                    <span className={`${s.badge} ${b.cls}`}>{b.label}</span>
                  </div>
                  <div className={s.meta}>
                    {item.category ?? "Menu"}
                    {item.price_aed != null ? ` · AED ${item.price_aed}` : ""}
                    {!item.is_available ? " · hidden" : ""}
                  </div>
                  {item.retailer_id ? (
                    <div className={s.rid}>Meta ID: {item.retailer_id}</div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}