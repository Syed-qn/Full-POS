import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import { apiClient } from "../lib/apiClient";
import { syncCatalog } from "../lib/catalogApi";
import type { RestaurantOut } from "../lib/types";
import { fetchUnifiedMenu, type UnifiedMenu } from "../lib/unifiedMenuApi";
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
  // Onboarding passes onCatalogIdSaved; the Menu page does not. On the Menu page the
  // catalog ID and server token are managed from the environment, so we hide all of
  // those setup details and just show the live publish/sync controls.
  const setupMode = onCatalogIdSaved !== undefined;
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

  if (loading)
    return (
      <div className={s.panel} aria-busy="true" aria-label="Loading WhatsApp menu">
        <div className={s.head}>
          <div className={s.skHeadText}>
            <span className={`${s.sk} ${s.skTitle}`} />
            <span className={`${s.sk} ${s.skLine}`} />
            <span className={`${s.sk} ${s.skLineShort}`} />
          </div>
          <div className={s.actions}>
            <span className={`${s.sk} ${s.skBtn}`} />
          </div>
        </div>
        <div className={s.stats}>
          {[70, 92, 86, 100].map((w, i) => (
            <span key={i} className={`${s.sk} ${s.skPill}`} style={{ width: w }} />
          ))}
        </div>
      </div>
    );

  return (
    <div className={s.panel}>
      <div className={s.head}>
        <div>
          <h3 className={s.title}>WhatsApp menu</h3>
          <p className={s.sub}>
            Your dishes publish to WhatsApp automatically when you edit them. Use{" "}
            <b>Pull from Meta</b> to refresh, so dishes still processing go live and anything
            deleted in Meta is cleared here.
          </p>
          {setupMode && (
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
                <li>That's it. Dishes publish automatically. Use <b>Pull from Meta</b> to refresh status.</li>
              </ol>
            </details>
          )}
        </div>
        <div className={s.actions}>
          <Button onClick={doPullOnly} disabled={syncing || !catalogId.trim()}>
            {syncing ? "Pulling…" : "Pull from Meta"}
          </Button>
        </div>
      </div>

      {setupMode && (
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
      )}

      {menu && menu.items.length > 0 ? (
        <div className={s.stats}>
          {(() => {
            const dishItems = menu.items.filter((i) => i.dish_id != null);
            const dishCount = dishItems.length;
            const availCount = dishItems.filter((i) => i.is_available).length;
            const catCount = new Set(dishItems.map((i) => i.category ?? "Other")).size;
            const linked = menu.items.filter((i) => i.link_status === "linked");
            const onWa = linked.filter((i) => i.sendable !== false).length;
            const inReview = linked.filter((i) => i.sendable === false).length;
            return (
              <>
                <span className={s.stat}><b>{dishCount}</b> dishes</span>
                <span className={s.stat}>
                  <span className={s.dot} /> {availCount} available
                </span>
                <span className={s.stat}><b>{catCount}</b> categories</span>
                <span className={s.statDivider} />
                <span className={`${s.stat} ${s.statOn}`}>
                  <span className={s.dot} /> {onWa} on WhatsApp
                </span>
                {inReview > 0 && (
                  <span className={`${s.stat} ${s.statReview}`}>{inReview} in review</span>
                )}
              </>
            );
          })()}
        </div>
      ) : null}

      {menu && menu.items.some((i) => i.link_status === "linked" && i.sendable === false) ? (
        <p className={s.hint}>
          Some dishes are still being processed by Meta. They go live on WhatsApp
          automatically. Click <b>Pull from Meta</b> to check if they're ready.
        </p>
      ) : null}
      {setupMode && !catalogId.trim() ? (
        <p className={s.hint}>
          Add your Meta Catalog ID above to start publishing your menu to WhatsApp.
        </p>
      ) : null}
    </div>
  );
}