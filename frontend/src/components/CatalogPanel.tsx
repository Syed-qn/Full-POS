import { useEffect, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import {
  fetchCatalogProducts,
  syncCatalog,
  type CatalogProductOut,
} from "../lib/catalogApi";
import s from "./CatalogPanel.module.css";

/** Catalogue mode panel for the Menu screen: a "Sync from Meta" button and the
 *  products mirrored from the restaurant's Meta Commerce catalogue. Shown only when
 *  catalogue ordering is on — in that mode the Meta catalogue (not the text menu) is
 *  what customers order from. */
export function CatalogPanel() {
  const [products, setProducts] = useState<CatalogProductOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [lastSynced, setLastSynced] = useState<string | null>(null);

  function load() {
    fetchCatalogProducts()
      .then((p) => {
        setProducts(p);
        const latest = p.map((x) => x.synced_at).filter(Boolean).sort().pop() ?? null;
        setLastSynced(latest);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function doSync() {
    setSyncing(true);
    try {
      const res = await syncCatalog();
      setProducts(res.products);
      const latest = res.products.map((x) => x.synced_at).filter(Boolean).sort().pop() ?? null;
      setLastSynced(latest);
      toast(
        `Synced from Meta · ${res.total_active} item${res.total_active === 1 ? "" : "s"}` +
          (res.added ? ` · ${res.added} new` : "") +
          (res.deactivated ? ` · ${res.deactivated} removed` : ""),
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "Sync failed", "error");
    } finally {
      setSyncing(false);
    }
  }

  const active = products.filter((p) => p.is_active);
  const inactive = products.filter((p) => !p.is_active);

  return (
    <div className={s.panel}>
      <div className={s.head}>
        <div>
          <h3 className={s.title}>Catalogue (from Meta)</h3>
          <p className={s.sub}>
            Customers order from your Meta catalogue. Set products in Meta Commerce
            Manager, then sync here.
            {lastSynced && (
              <span className={s.synced}> Last synced {fmt(lastSynced)}.</span>
            )}
          </p>
        </div>
        <Button onClick={doSync} disabled={syncing}>
          {syncing ? "Syncing…" : "Sync from Meta"}
        </Button>
      </div>

      {loading ? (
        <p className={s.empty}>Loading…</p>
      ) : active.length === 0 ? (
        <p className={s.empty}>
          No products yet. Click <b>Sync from Meta</b> to pull your catalogue.
        </p>
      ) : (
        <div className={s.grid}>
          {active.map((p) => (
            <div key={p.id} className={s.card}>
              {p.image_url ? (
                <img className={s.thumb} src={p.image_url} alt={p.name} />
              ) : (
                <div className={s.thumbPlaceholder}>🍽️</div>
              )}
              <div className={s.cardBody}>
                <span className={s.name}>{p.name}</span>
                <span className={s.meta}>
                  {p.price_aed != null ? `AED ${p.price_aed}` : "—"}
                  {p.availability && p.availability !== "in stock" && (
                    <span className={s.oos}> · {p.availability}</span>
                  )}
                </span>
                <span className={s.rid}>{p.retailer_id}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {inactive.length > 0 && (
        <p className={s.removed}>
          {inactive.length} product{inactive.length === 1 ? "" : "s"} no longer in Meta
          (hidden from customers).
        </p>
      )}
    </div>
  );
}

function fmt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "recently";
  return d.toLocaleString();
}
