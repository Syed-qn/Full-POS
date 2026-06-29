import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import { apiClient } from "../lib/apiClient";
import { syncCatalog } from "../lib/catalogApi";
import type { RestaurantOut } from "../lib/types";
import { fetchUnifiedMenu, syncCatalogFull, type UnifiedMenu } from "../lib/unifiedMenuApi";
import s from "./UnifiedMenuPanel.module.css";

export function UnifiedMenuPanel({
  onCatalogIdSaved,
  refreshSignal,
  onChanged,
  onMenuLoaded,
}: {
  onCatalogIdSaved?: () => void;
  /** Bumped by the parent after a dish edit/delete/availability toggle so the
   *  unified view re-fetches and never shows a stale price (e.g. AED 20 vs 30). */
  refreshSignal?: number;
  /** Called after a Meta sync that may have created/linked dishes, so the parent
   *  reloads its dish list. */
  onChanged?: () => void;
  /** Hands the loaded unified menu to the parent so it can show per-dish
   *  "On WhatsApp" status inline on the single dish list (no duplicate grid). */
  onMenuLoaded?: (menu: UnifiedMenu) => void;
}) {
  const [menu, setMenu] = useState<UnifiedMenu | null>(null);
  const [catalogId, setCatalogId] = useState("");
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [savingId, setSavingId] = useState(false);
  // Keep the callback in a ref so `load` stays referentially stable (no refetch loop
  // if the parent passes a fresh function each render).
  const onMenuLoadedRef = useRef(onMenuLoaded);
  onMenuLoadedRef.current = onMenuLoaded;

  const load = useCallback(async () => {
    try {
      const [unified, me] = await Promise.all([
        fetchUnifiedMenu(),
        apiClient.get<RestaurantOut>("/api/v1/me"),
      ]);
      setMenu(unified);
      onMenuLoadedRef.current?.(unified);
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

  // Re-fetch when the parent signals a dish change (edit/delete/toggle). Skip the
  // initial 0 so this doesn't double-load on mount.
  useEffect(() => {
    if (refreshSignal) load();
  }, [refreshSignal, load]);

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
      if (res.push_errors?.length) {
        toast(res.push_errors.join("; "), "error");
        return;
      }
      toast(
        `Synced · ${res.total_active} in Meta` +
          (res.pushed ? ` · ${res.pushed} pushed` : "") +
          (res.push_updated ? ` · ${res.push_updated} updated` : "") +
          (res.linked ? ` · ${res.linked} linked` : ""),
      );
      await load();
      onChanged?.();
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
      onChanged?.();
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
          <h3 className={s.title}>WhatsApp menu</h3>
          <p className={s.sub}>
            One menu. Dishes publish to WhatsApp automatically when you activate a menu —
            customers who ask for the menu get tappable catalogue cards. Use{" "}
            <b>Publish to WhatsApp</b> to push changes right now.
          </p>
          <details className={s.guide}>
            <summary>How to create a Meta catalogue</summary>
            <ol>
              <li>Open Meta Commerce Manager → Catalogues → Create catalogue.</li>
              <li>Connect the catalogue to your WhatsApp Business Account.</li>
              <li>Copy the Catalogue ID and paste it below.</li>
              <li>
                Set <code>APP_WA_CATALOG_TOKEN</code> on the server (system user with{" "}
                <code>catalog_management</code>).
              </li>
              <li>That's it — dishes publish automatically on menu activation. <b>Publish to WhatsApp</b> pushes changes on demand.</li>
            </ol>
          </details>
        </div>
        <div className={s.actions}>
          <Button onClick={doSyncFull} disabled={syncing || !catalogId.trim()}>
            {syncing ? "Publishing…" : "Publish to WhatsApp"}
          </Button>
          <button
            type="button"
            className={s.advancedLink}
            onClick={doPullOnly}
            disabled={syncing || !catalogId.trim()}
          >
            Pull from Meta
          </button>
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

      {menu && menu.items.length > 0 ? (
        <div className={s.stats}>
          <span className={`${s.stat} ${s.statOn}`}>
            <span className={s.dot} /> {menu.linked_count} on WhatsApp
          </span>
          {menu.dish_only_count > 0 && (
            <span className={s.stat}>{menu.dish_only_count} not published yet</span>
          )}
          {menu.catalog_only_count > 0 && (
            <span className={s.stat}>{menu.catalog_only_count} only in Meta</span>
          )}
        </div>
      ) : null}

      {menu && menu.dish_only_count > 0 && catalogId.trim() ? (
        <p className={s.hint}>
          {menu.dish_only_count} dish{menu.dish_only_count > 1 ? "es" : ""} not on WhatsApp yet —
          click <b>Publish to WhatsApp</b> to push {menu.dish_only_count > 1 ? "them" : "it"} live.
        </p>
      ) : null}
      {!catalogId.trim() ? (
        <p className={s.hint}>
          Add your Meta Catalog ID above to start publishing your menu to WhatsApp.
        </p>
      ) : null}
    </div>
  );
}