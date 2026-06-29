import { useCallback, useEffect, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import { apiClient } from "../lib/apiClient";
import { syncCatalog } from "../lib/catalogApi";
import type { RestaurantOut } from "../lib/types";
import { fetchUnifiedMenu, syncCatalogFull, type UnifiedMenu } from "../lib/unifiedMenuApi";
import s from "./UnifiedMenuPanel.module.css";

// Manager-facing status — no Meta jargon. Everything publishes automatically on
// menu activation; "Not yet" just means it hasn't been pushed since its last edit.
const BADGE: Record<string, { label: string; cls: string }> = {
  linked: { label: "On WhatsApp", cls: s.linked },
  dish_only: { label: "Not on WhatsApp yet", cls: s.dishOnly },
  catalog_only: { label: "Meta only", cls: s.catOnly },
};

export function UnifiedMenuPanel({
  onCatalogIdSaved,
  refreshSignal,
  onChanged,
}: {
  onCatalogIdSaved?: () => void;
  /** Bumped by the parent after a dish edit/delete/availability toggle so the
   *  unified view re-fetches and never shows a stale price (e.g. AED 20 vs 30). */
  refreshSignal?: number;
  /** Called after a Meta sync that may have created/linked dishes, so the parent
   *  reloads its dish list. */
  onChanged?: () => void;
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