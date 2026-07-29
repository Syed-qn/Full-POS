import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
import { KitchenAddModal } from "../components/KitchenAddModal";
import { PageHeader } from "../components/PageHeader";
import { toast } from "../components/Toaster";
import {
  createStation,
  deleteStation,
  fetchCategoryDefaults,
  fetchStations,
  patchStation,
  unwireCategory,
  wireCategory,
  type CategoryDefault,
  type KdsStation,
} from "../lib/kdsApi";
import { useLiveMenu } from "../lib/useLiveMenu";
import s from "./KitchensScreen.module.css";

const MAIN = "Main";

/**
 * Manager "Kitchens" — create kitchen boards and route dishes to them.
 *
 * A kitchen is a KDS station. One kitchen named "Main" is the routing fallback:
 * any dish not wired by category (or pinned on the dish itself) lands there, so
 * a ticket is never lost. Managers wire whole categories here; per-dish overrides
 * live in the dish editor.
 */
export function KitchensScreen() {
  const navigate = useNavigate();
  const { dishes } = useLiveMenu({ cache: true });
  const [stations, setStations] = useState<KdsStation[]>([]);
  const [defaults, setDefaults] = useState<CategoryDefault[]>([]);
  const [adding, setAdding] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      let st = await fetchStations();
      // Guarantee the Main fallback exists so routing always has a home.
      if (!st.some((x) => x.name === MAIN)) {
        await createStation({ name: MAIN, station_type: "main" });
        st = await fetchStations();
      }
      setStations(st);
      setDefaults(await fetchCategoryDefaults());
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load kitchens", "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const d of dishes) {
      const c = (d.category || "").trim();
      if (c) set.add(c);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [dishes]);

  const mainId = stations.find((x) => x.name === MAIN)?.id ?? null;
  // Main leads (it is the fallback everything falls back to), then the rest by name.
  const orderedStations = useMemo(() => {
    const rest = stations
      .filter((x) => x.name !== MAIN)
      .sort((a, b) => a.name.localeCompare(b.name));
    const main = stations.find((x) => x.name === MAIN);
    return main ? [main, ...rest] : rest;
  }, [stations]);
  // Plain name match, Main included. Pinning Main so it always showed was
  // tempting — it is the fallback — but then a query matching nothing still
  // returned one tile, so "no kitchen matches" could never be reached and a
  // typo looked like a real result.
  const shownStations = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return orderedStations;
    return orderedStations.filter((x) => x.name.toLowerCase().includes(q));
  }, [orderedStations, query]);

  const categoryToStation = useMemo(() => {
    const m = new Map<string, number>();
    for (const d of defaults) m.set(d.category, d.station_id);
    return m;
  }, [defaults]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed", "error");
    } finally {
      setBusy(false);
    }
  }

  function addKitchen(name: string) {
    setAdding(false);
    void run(async () => {
      await createStation({ name });
      toast(`Kitchen "${name}" added.`);
    });
  }

  function renameKitchen(st: KdsStation, name: string) {
    setEditingId(null);
    const next = name.trim();
    if (!next || next === st.name) return;
    void run(() => patchStation(st.id, { name: next }));
  }

  function removeKitchen(st: KdsStation) {
    void run(async () => {
      await deleteStation(st.id);
      toast(`Kitchen "${st.name}" removed. Its dishes route to Main.`);
    });
  }

  function routeCategory(category: string, stationId: number | null) {
    void run(async () => {
      if (stationId === null || stationId === mainId) {
        // Main is the fallback, so "route to Main" just means un-wiring.
        if (categoryToStation.has(category)) await unwireCategory(category);
      } else {
        await wireCategory(category, stationId);
      }
    });
  }

  const otherKitchens = stations.filter((x) => x.name !== MAIN);

  return (
    <div className={s.screen}>
      <PageHeader
        title="Kitchens"
        subtitle="Create kitchen boards and route dishes to them by category. Anything not wired goes to the Main kitchen."
        right={
          <Button size="md" disabled={busy} onClick={() => setAdding(true)} data-testid="kitchen-add-open">
            + Add kitchen
          </Button>
        }
      />

      {/* ── Kitchens ─────────────────────────────────────────────────── */}
      <section className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h3 className={s.cardTitle}>Kitchens</h3>
            <span className={s.cardSub}>Each kitchen has its own KDS board</span>
          </div>
          {!loading && orderedStations.length > 0 && (
            <input
              className={s.search}
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter kitchens"
              aria-label="Filter kitchens"
              data-testid="kitchen-filter"
            />
          )}
        </div>

        {loading ? (
          /* The real grid's shape with shimmer tiles, so the page does not jump
             when the kitchens land. */
          <div className={s.kGrid} aria-busy="true" aria-label="Loading kitchens">
            {Array.from({ length: 3 }).map((_, i) => (
              <div className={s.kTile} key={i}>
                <div className={s.kTileTop}>
                  <span className={s.sk} style={{ width: 38, height: 38, borderRadius: 10 }} />
                  <span className={s.sk} style={{ width: "45%" }} />
                </div>
                <span className={s.sk} style={{ width: "70%" }} />
                <div className={s.kActions}>
                  <span className={s.sk} style={{ width: 60 }} />
                  <span className={s.sk} style={{ width: 80 }} />
                </div>
              </div>
            ))}
          </div>
        ) : shownStations.length === 0 ? (
          <p className={s.muted}>No kitchen matches “{query.trim()}”.</p>
        ) : (
          <div className={s.kGrid}>
            {shownStations.map((st) => {
              const isMain = st.name === MAIN;
              const wiredCount = defaults.filter((d) => d.station_id === st.id).length;
              const editing = editingId === st.id;
              return (
                <div
                  className={`${s.kTile} ${isMain ? s.kTileMain : ""}`}
                  key={st.id}
                >
                  <div className={s.kTileTop}>
                    <span className={s.kIcon} aria-hidden>
                      {isMain ? "🍳" : "🍽️"}
                    </span>
                    {editing ? (
                      <input
                        className={s.kNameInput}
                        defaultValue={st.name}
                        disabled={busy}
                        autoFocus
                        aria-label={`Kitchen name (${st.name})`}
                        onBlur={(e) => renameKitchen(st, e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                          if (e.key === "Escape") setEditingId(null);
                        }}
                      />
                    ) : (
                      <div className={s.kNameWrap}>
                        <span className={s.kName}>{st.name}</span>
                        {isMain && <span className={s.mainBadge}>Fallback</span>}
                      </div>
                    )}
                  </div>

                  <span className={s.kMeta}>
                    {isMain
                      ? "Catches anything not routed elsewhere"
                      : `${wiredCount} categor${wiredCount === 1 ? "y" : "ies"} routed here`}
                  </span>

                  <div className={s.kActions}>
                    {isMain ? (
                      <span className={s.kNote}>Protected</span>
                    ) : (
                      <>
                        <button
                          type="button"
                          className={s.linkBtn}
                          disabled={busy || editing}
                          onClick={() => setEditingId(st.id)}
                          data-testid={`kitchen-rename-${st.id}`}
                        >
                          Rename
                        </button>
                        <button
                          type="button"
                          className={s.linkBtnDanger}
                          disabled={busy}
                          onClick={() => removeKitchen(st)}
                          data-testid={`kitchen-delete-${st.id}`}
                        >
                          Remove
                        </button>
                      </>
                    )}
                    <span className={s.kSpacer} />
                    <button
                      type="button"
                      className={s.openLink}
                      onClick={() => navigate(`/kds/${st.id}`)}
                      data-testid={`kitchen-open-${st.id}`}
                    >
                      Open board →
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ── Category routing ─────────────────────────────────────────── */}
      <section className={s.card}>
        <div className={s.cardHead}>
          <div className={s.cardHeadText}>
            <h3 className={s.cardTitle}>Route categories</h3>
            <span className={s.cardSub}>
              Pick which kitchen cooks each menu category. Anything left on Main
              goes to the fallback board.
            </span>
          </div>
        </div>

        {categories.length === 0 ? (
          <p className={s.muted}>No menu categories yet.</p>
        ) : (
          <div className={s.wireTable}>
            {categories.map((cat) => {
              // A category wired straight to Main is just the default — treat it
              // the same as "no row" so it isn't shown as specially routed (and
              // the <select>, whose only options are "" and the OTHER kitchens,
              // matches instead of falling back to the first option).
              const wired = categoryToStation.get(cat);
              const current = wired != null && wired !== mainId ? wired : "";
              const destName =
                otherKitchens.find((k) => k.id === current)?.name ?? MAIN;
              const routed = current !== "";
              return (
                <div className={s.wireRow} key={cat}>
                  <span className={s.wireCat}>
                    <span className={s.wireCatName}>{cat}</span>
                    <span
                      className={`${s.wireCatDest} ${routed ? s.wireCatDestActive : ""}`}
                    >
                      → {destName}
                    </span>
                  </span>
                  <select
                    className={s.wireSelect}
                    value={current}
                    disabled={busy}
                    onChange={(e) =>
                      routeCategory(cat, e.target.value === "" ? null : Number(e.target.value))
                    }
                    data-testid={`wire-${cat}`}
                  >
                    <option value="">Main (default)</option>
                    {otherKitchens.map((k) => (
                      <option key={k.id} value={k.id}>
                        {k.name}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {adding && (
        <KitchenAddModal
          existingNames={stations.map((x) => x.name)}
          busy={busy}
          onClose={() => setAdding(false)}
          onSubmit={addKitchen}
        />
      )}
    </div>
  );
}
