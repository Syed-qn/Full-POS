import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { UnifiedMenu } from "../lib/unifiedMenuApi";
import { Button } from "../components/Button";
import { MenuReviewDialog } from "../components/MenuReviewDialog";
import { Spinner } from "../components/Spinner";
import { DishCard } from "../components/DishCard";
import { DishEditModal } from "../components/DishEditModal";
import { SectionBanner } from "../components/SectionBanner";
import { ApiError } from "../lib/apiClient";
import {
  activateMenu,
  createBlankMenu,
  createPriceRule,
  deleteDish,
  deletePriceRule,
  fetchActiveMenu,
  getMenu,
  listPriceRules,
  setAvailability,
  setWhatsapp,
  uploadMenu,
} from "../lib/menuApi";
import { toast } from "../components/Toaster";
import type { DishOut, MenuWithDiffOut, PriceRuleOut } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import { UnifiedMenuPanel } from "../components/UnifiedMenuPanel";
import s from "./MenuManagerScreen.module.css";

export function MenuManagerScreen({ initialMenuId }: { initialMenuId?: number }) {
  const [dishes, setDishes] = useState<DishOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<MenuWithDiffOut | null>(null);
  // True while Claude is extracting an uploaded menu (before the review dialog opens).
  const [extracting, setExtracting] = useState(false);
  const [activeMenuId, setActiveMenuId] = useState<number | null>(initialMenuId ?? null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<DishOut | "new" | null>(null);
  // Bumped on every dish mutation so the unified/catalog panel re-fetches and can
  // never show a stale price (the AED 20-vs-30 bug).
  const [menuRev, setMenuRev] = useState(0);
  // dish_ids that are LIVE on the WhatsApp catalogue (Meta finished processing the
  // image) — shown inline on each dish so there's ONE menu list (no duplicate grid).
  const [waLinkedIds, setWaLinkedIds] = useState<Set<number>>(new Set());
  // dish_ids linked to a catalogue product that is still IN REVIEW (image processing) —
  // kept off WhatsApp until ready, shown with an "In review" pill.
  const [waReviewIds, setWaReviewIds] = useState<Set<number>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);

  const onMenuLoaded = useCallback((m: UnifiedMenu) => {
    const linked = m.items.filter((i) => i.link_status === "linked" && i.dish_id != null);
    setWaLinkedIds(
      new Set(linked.filter((i) => i.sendable !== false).map((i) => i.dish_id as number)),
    );
    setWaReviewIds(
      new Set(linked.filter((i) => i.sendable === false).map((i) => i.dish_id as number)),
    );
  }, []);

  function reloadDishes() {
    if (activeMenuId !== null) {
      getMenu(activeMenuId).then((m) => setDishes(m.dishes ?? [])).catch(() => {});
    } else {
      fetchActiveMenu()
        .then((m) => {
          if (m) {
            setActiveMenuId(m.id);
            setDishes(m.dishes ?? []);
          }
        })
        .catch(() => {});
    }
    setMenuRev((v) => v + 1);
  }

  // Add/edit save: paint the saved dish into the list instantly from the API response
  // (upsert), then refetch for authority. Soft — no browser reload.
  function onDishSaved(saved?: DishOut) {
    if (saved) {
      setDishes((ds) =>
        ds.some((d) => d.id === saved.id)
          ? ds.map((d) => (d.id === saved.id ? saved : d))
          : [...ds, saved],
      );
    }
    reloadDishes();
  }

  useEffect(() => {
    if (pending !== null) return;
    if (activeMenuId !== null) {
      // Known menu id (after an upload+activate, or passed in): load its dishes.
      getMenu(activeMenuId).then((m) => setDishes(m.dishes ?? [])).catch(() => {}).finally(() => setLoading(false));
    } else {
      // First mount with no id: discover the restaurant's active menu so the
      // current dishes show up instead of the empty "upload your first menu"
      // state. Without this the screen never loads an existing/seeded menu.
      fetchActiveMenu()
        .then((m) => {
          if (m) {
            setActiveMenuId(m.id);
            setDishes(m.dishes ?? []);
          }
        })
        .catch(() => {})
        .finally(() => setLoading(false));
    }
  }, [activeMenuId, pending]);

  async function onDeleteDish(dish: DishOut) {
    if (activeMenuId === null) return;
    if (!window.confirm(`Remove “${dish.name}” from the menu? It will also be removed from WhatsApp.`)) return;
    try {
      await deleteDish(activeMenuId, dish.id);
      setDishes((ds) => ds.filter((d) => d.id !== dish.id));
      setMenuRev((v) => v + 1);
      toast(`“${dish.name}” removed from the menu.`);
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Failed to remove dish.", "error");
    }
  }

  async function onAddDish() {
    // Works even on a fresh restaurant: create an empty active menu on the fly, then
    // open the editor so the manager can add the first dish without uploading a file.
    if (activeMenuId === null) {
      try {
        const menu = await createBlankMenu();
        setActiveMenuId(menu.id);
      } catch (err) {
        toast(err instanceof ApiError ? err.detail : "Couldn't start a menu.", "error");
        return;
      }
    }
    setEditing("new");
  }

  async function onToggle(id: number, next: boolean) {
    setDishes((ds) => ds.map((d) => (d.id === id ? { ...d, is_available: next } : d)));
    try {
      await setAvailability(id, next);
      setMenuRev((v) => v + 1); // refresh unified/WhatsApp view with new availability
    } catch {
      setDishes((ds) => ds.map((d) => (d.id === id ? { ...d, is_available: !next } : d)));
      setError("Failed to update availability.");
    }
  }

  async function onWhatsappToggle(id: number, next: boolean) {
    // Optimistic flip; the unified panel re-fetch updates the live/review badge.
    setDishes((ds) => ds.map((d) => (d.id === id ? { ...d, whatsapp_enabled: next } : d)));
    try {
      await setWhatsapp(id, next);
      toast(next ? "Dish turned on for WhatsApp." : "Dish hidden from WhatsApp.");
      setMenuRev((v) => v + 1);
    } catch {
      setDishes((ds) => ds.map((d) => (d.id === id ? { ...d, whatsapp_enabled: !next } : d)));
      toast("Failed to update WhatsApp setting.", "error");
    }
  }

  async function onUpload(files: FileList | null) {
    if (!files || files.length === 0) return;
    setExtracting(true);
    try {
      const result = await uploadMenu(Array.from(files));
      setPending(result);
    } catch {
      setError("Menu upload failed.");
    } finally {
      setExtracting(false);
    }
  }

  const [confirming, setConfirming] = useState(false);
  async function onConfirm() {
    if (!pending) return;
    setConfirming(true);
    try {
      // Uploading APPENDS the reviewed dishes into the current menu (bulk add), so the
      // active menu that now holds them may differ from the just-uploaded draft id — use
      // the id the server returns, not pending.id (which becomes an emptied draft).
      const activated = await activateMenu(pending.id);
      // Soft refresh — no browser reload needed. The activate response already carries the
      // updated menu, so paint its dishes immediately; bump menuRev so the WhatsApp/catalog
      // panel refetches too. (The pending→null effect also refetches via getMenu as backup.)
      setActiveMenuId(activated.id);
      setDishes(activated.dishes ?? []);
      setMenuRev((v) => v + 1);
      setPending(null);
    } catch {
      setError("Could not activate the menu.");
    } finally {
      setConfirming(false);
    }
  }

  const hasErrors = (pending?.diff_vs_active?.conflicts.length ?? 0) > 0;

  // Next free dish number — assigned automatically to new dishes.
  const nextNumber = dishes.length
    ? Math.max(...dishes.map((d) => d.dish_number ?? 0)) + 1
    : 1;

  // Filters
  const [search, setSearch] = useState("");
  const [catFilter, setCatFilter] = useState<string>("all");
  const [availFilter, setAvailFilter] = useState<"all" | "available" | "hidden">("all");

  const allCategories = useMemo(
    () => Array.from(new Set(dishes.map((d) => d.category ?? "Other"))).sort(),
    [dishes],
  );

  const filteredDishes = useMemo(() => {
    const q = search.trim().toLowerCase();
    return dishes.filter((d) => {
      if (catFilter !== "all" && (d.category ?? "Other") !== catFilter) return false;
      if (availFilter === "available" && !d.is_available) return false;
      if (availFilter === "hidden" && d.is_available) return false;
      if (q) {
        return (
          d.name.toLowerCase().includes(q) ||
          String(d.dish_number ?? "").includes(q)
        );
      }
      return true;
    });
  }, [dishes, search, catFilter, availFilter]);

  // Group the filtered dishes into category sections, preserving dish-number order.
  const grouped = useMemo(() => {
    const map = new Map<string, DishOut[]>();
    for (const d of filteredDishes) {
      const cat = d.category ?? "Other";
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(d);
    }
    return Array.from(map.entries())
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([cat, items]) => ({
        cat,
        items: [...items].sort((a, b) => (a.dish_number ?? 0) - (b.dish_number ?? 0)),
      }));
  }, [filteredDishes]);

  if (pending) {
    return (
      <MenuReviewDialog
        menu={pending}
        onClose={() => setPending(null)}
        onConfirm={onConfirm}
        confirming={confirming}
        hasErrors={hasErrors}
      />
    );
  }

  return (
    <div className={s.screen}>
      {extracting && (
        <div className={s.extractOverlay} role="status" aria-live="polite">
          <div className={s.extractCard}>
            <div className={s.extractSpin}>
              <Spinner label="Reading menu" />
            </div>
            <h3 className={s.extractTitle}>Reading your menu…</h3>
            <p className={s.extractInfo}>
              Our AI is pulling out dish names, numbers, prices, and sizes. This usually
              takes a few seconds — the review screen opens automatically when it's done.
            </p>
          </div>
        </div>
      )}
      {error && <SectionBanner tone="error" onDismiss={() => setError(null)}>{error}</SectionBanner>}
      <PageHeader
        title="Menu"
        subtitle="One menu. Edit here and it publishes to WhatsApp automatically. Customers who ask for the menu get tappable cards."
        right={
          <>
            <input
              ref={fileRef}
              type="file"
              multiple
              hidden
              onChange={(e) => onUpload(e.target.files)}
              data-testid="menu-upload"
            />
            <Button variant="ghost" onClick={onAddDish}>+ Add dish</Button>
            <Button onClick={() => fileRef.current?.click()}>
              {dishes.length > 0 ? "Upload new menu" : "Upload menu"}
            </Button>
          </>
        }
      />
      <UnifiedMenuPanel refreshSignal={menuRev} onChanged={reloadDishes} onMenuLoaded={onMenuLoaded} />
      {loading ? (
        <MenuSkeleton />
      ) : dishes.length === 0 ? (
        <div className={s.empty}>
          <p>Upload your first menu (PDF, image, or text) to get started.</p>
          <Button onClick={() => fileRef.current?.click()}>Upload menu</Button>
        </div>
      ) : (
        <>
          <div className={s.filterBar}>
            <div className={`${s.filterGroup} ${s.grow}`}>
              <span className={s.filterLabel}>Search</span>
              <input
                className={s.search}
                placeholder="Search dish name or #number"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className={`${s.filterGroup} ${s.pushRight}`}>
              <span className={s.filterLabel}>Availability</span>
              <div className={s.segment}>
                {(["all", "available", "hidden"] as const).map((a) => (
                  <button
                    key={a}
                    className={`${s.segBtn} ${availFilter === a ? s.segBtnActive : ""}`}
                    onClick={() => setAvailFilter(a)}
                  >
                    {a === "all" ? "All" : a === "available" ? "Available" : "Unavailable"}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className={s.filterGroup}>
            <span className={s.filterLabel}>Category</span>
            <div className={s.chips}>
              <button
                className={`${s.chip} ${catFilter === "all" ? s.chipActive : ""}`}
                onClick={() => setCatFilter("all")}
              >
                All
              </button>
              {allCategories.map((c) => (
                <button
                  key={c}
                  className={`${s.chip} ${catFilter === c ? s.chipActive : ""}`}
                  onClick={() => setCatFilter(c)}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>

          {grouped.length === 0 ? (
            <div className={s.empty}>No dishes match your filters.</div>
          ) : (
            grouped.map(({ cat, items }) => (
            <section key={cat} className={s.catSection}>
              <div className={s.catHeader}>
                <span className={s.catName}>{cat}</span>
                <span className={s.catCount}>{items.length}</span>
              </div>
              <div className={s.grid}>
                {items.map((d) => (
                  <div key={d.id} className={s.dragItem}>
                    <DishCard dish={d} onToggle={onToggle} onEdit={setEditing} onDelete={onDeleteDish} onWhatsapp={waLinkedIds.has(d.id)} inReview={waReviewIds.has(d.id)} onWhatsappToggle={onWhatsappToggle} />
                  </div>
                ))}
              </div>
            </section>
            ))
          )}
        </>
      )}

      {editing !== null && activeMenuId !== null && (
        <DishEditModal
          menuId={activeMenuId}
          dish={editing}
          categories={allCategories}
          nextNumber={nextNumber}
          onClose={() => setEditing(null)}
          onSaved={onDishSaved}
        />
      )}
      {editing !== null && editing !== "new" && <PriceRulesPanel dish={editing} />}
    </div>
  );
}

/** Time/channel/branch price overrides for the currently-selected dish. Rendered
 *  alongside the edit modal (not inside it) so it works independent of the
 *  base-dish save flow — a manager can add/remove rules without touching name,
 *  price, or category. */
function PriceRulesPanel({ dish }: { dish: DishOut }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rules, setRules] = useState<PriceRuleOut[]>([]);
  const [ruleType, setRuleType] = useState<"time" | "channel" | "branch">("channel");
  const [priceAed, setPriceAed] = useState("");
  const [channel, setChannel] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setRules(await listPriceRules(dish.id));
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Failed to load price rules.", "error");
    } finally {
      setLoading(false);
    }
  }

  async function onToggleOpen() {
    const next = !open;
    setOpen(next);
    if (next) await load();
  }

  async function onDeleteRule(ruleId: number) {
    try {
      await deletePriceRule(dish.id, ruleId);
      setRules((rs) => rs.filter((r) => r.id !== ruleId));
      toast("Price rule removed.");
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Failed to delete price rule.", "error");
    }
  }

  async function onAddRule() {
    if (!priceAed.trim()) return;
    setBusy(true);
    try {
      const created = await createPriceRule(dish.id, {
        rule_type: ruleType,
        price_aed: priceAed.trim(),
        channel: ruleType === "channel" ? channel.trim() || null : null,
      });
      setRules((rs) => [...rs, created]);
      setPriceAed("");
      setChannel("");
      toast("Price rule added.");
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Failed to add price rule.", "error");
    } finally {
      setBusy(false);
    }
  }

  function describeRule(r: PriceRuleOut): string {
    const parts: string[] = [r.rule_type];
    if (r.channel) parts.push(r.channel);
    if (r.start_time && r.end_time) parts.push(`${r.start_time}–${r.end_time}`);
    parts.push(`AED ${r.price_aed}`);
    return parts.join(" · ");
  }

  return (
    <div className={s.priceRulesPanel}>
      <button type="button" className={s.priceRulesToggle} onClick={onToggleOpen}>
        Price rules
      </button>
      {open && (
        <div className={s.priceRulesBody}>
          {loading ? (
            <span className={s.hint}>Loading price rules…</span>
          ) : rules.length === 0 ? (
            <p className={s.hint}>No price rules yet for this dish.</p>
          ) : (
            <ul className={s.priceRulesList}>
              {rules.map((r) => (
                <li key={r.id} className={s.priceRuleRow}>
                  <span>{describeRule(r)}</span>
                  <button type="button" onClick={() => onDeleteRule(r.id)}>
                    Delete rule
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className={s.priceRuleForm}>
            <select
              className={s.priceRuleSelect}
              value={ruleType}
              onChange={(e) => setRuleType(e.target.value as "time" | "channel" | "branch")}
              aria-label="Rule type"
            >
              <option value="channel">Channel</option>
              <option value="time">Time</option>
              <option value="branch">Branch</option>
            </select>
            {ruleType === "channel" && (
              <input
                className={s.priceRuleInput}
                placeholder="Channel (e.g. aggregator)"
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                aria-label="Channel"
              />
            )}
            <input
              className={s.priceRuleInput}
              type="number"
              step="0.01"
              placeholder="Price AED"
              value={priceAed}
              onChange={(e) => setPriceAed(e.target.value)}
              aria-label="Price AED"
            />
            <button type="button" onClick={onAddRule} disabled={busy || !priceAed.trim()}>
              Add rule
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// Skeleton placeholder mirroring the menu layout (filters, chips, and category
// grids of dish cards) so the page keeps its shape while loading. Stats now live
// in the WhatsApp menu panel above, which has its own loading state.
function MenuSkeleton() {
  return (
    <div className={s.skWrap} aria-busy="true" aria-label="Loading menu">
      <div className={s.filterBar}>
        <div className={`${s.filterGroup} ${s.grow}`}>
          <span className={`${s.sk} ${s.skLabel}`} />
          <span className={`${s.sk} ${s.skSearch}`} />
        </div>
        <div className={`${s.filterGroup} ${s.pushRight}`}>
          <span className={`${s.sk} ${s.skLabel}`} />
          <span className={`${s.sk} ${s.skSegment}`} />
        </div>
      </div>
      <div className={s.filterGroup}>
        <span className={`${s.sk} ${s.skLabel}`} />
        <div className={s.chips}>
          {[44, 68, 56, 80, 50, 64].map((w, i) => (
            <span key={i} className={`${s.sk} ${s.skChip}`} style={{ width: w }} />
          ))}
        </div>
      </div>
      {Array.from({ length: 2 }).map((_, c) => (
        <section key={c} className={s.catSection}>
          <div className={s.catHeader}>
            <span className={`${s.sk} ${s.skCatName}`} />
          </div>
          <div className={s.grid}>
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className={s.skCard}>
                <span className={`${s.sk} ${s.skCardLine}`} style={{ width: "65%" }} />
                <span className={`${s.sk} ${s.skCardLine}`} style={{ width: "35%" }} />
                <span className={`${s.sk} ${s.skCardLine}`} style={{ width: "50%" }} />
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
