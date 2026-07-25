import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/Button";
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
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

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

  function addKitchen() {
    const name = newName.trim();
    if (!name) return;
    if (stations.some((x) => x.name.toLowerCase() === name.toLowerCase())) {
      toast("A kitchen with that name already exists.", "error");
      return;
    }
    void run(async () => {
      await createStation({ name });
      setNewName("");
      toast(`Kitchen "${name}" added.`);
    });
  }

  function renameKitchen(st: KdsStation, name: string) {
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
      />

      {/* ── Kitchens ─────────────────────────────────────────────────── */}
      <section className={s.card}>
        <div className={s.cardHead}>
          <h3 className={s.cardTitle}>Kitchens</h3>
          <span className={s.cardSub}>Each kitchen has its own KDS board</span>
        </div>

        {loading ? (
          <p className={s.muted}>Loading…</p>
        ) : (
          <div className={s.kList}>
            {stations.map((st) => {
              const isMain = st.name === MAIN;
              const wiredCount = defaults.filter((d) => d.station_id === st.id).length;
              return (
                <div className={s.kRow} key={st.id}>
                  {isMain ? (
                    <span className={s.kName}>
                      {st.name} <span className={s.mainBadge}>Fallback</span>
                    </span>
                  ) : (
                    <input
                      className={s.kNameInput}
                      defaultValue={st.name}
                      disabled={busy}
                      aria-label={`Kitchen name (${st.name})`}
                      onBlur={(e) => renameKitchen(st, e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                      }}
                    />
                  )}
                  <span className={s.kMeta}>
                    {wiredCount} categor{wiredCount === 1 ? "y" : "ies"}
                  </span>
                  <div className={s.kActions}>
                    <Button
                      variant="ghost"
                      onClick={() => navigate(`/kds/${st.id}`)}
                      data-testid={`kitchen-open-${st.id}`}
                    >
                      Open board →
                    </Button>
                    {isMain ? (
                      <span className={s.kNote}>Cannot be removed</span>
                    ) : (
                      <Button
                        variant="ghost"
                        disabled={busy}
                        onClick={() => removeKitchen(st)}
                        data-testid={`kitchen-delete-${st.id}`}
                      >
                        Remove
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className={s.addRow}>
          <input
            className={s.addInput}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="New kitchen name (e.g. Juice)"
            aria-label="New kitchen name"
            disabled={busy}
            onKeyDown={(e) => {
              if (e.key === "Enter") addKitchen();
            }}
            data-testid="kitchen-new-name"
          />
          <Button disabled={busy || newName.trim() === ""} onClick={addKitchen}>
            Add kitchen
          </Button>
        </div>
      </section>

      {/* ── Category routing ─────────────────────────────────────────── */}
      <section className={s.card}>
        <div className={s.cardHead}>
          <h3 className={s.cardTitle}>Route categories</h3>
          <span className={s.cardSub}>
            Pick which kitchen cooks each category. Default is Main.
          </span>
        </div>

        {categories.length === 0 ? (
          <p className={s.muted}>No menu categories yet.</p>
        ) : (
          <div className={s.wireTable}>
            {categories.map((cat) => {
              const current = categoryToStation.get(cat) ?? "";
              return (
                <div className={s.wireRow} key={cat}>
                  <span className={s.wireCat}>{cat}</span>
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
    </div>
  );
}
