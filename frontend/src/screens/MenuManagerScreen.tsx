import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { UnifiedMenu } from "../lib/unifiedMenuApi";
import { Button } from "../components/Button";
import { DiffPanel } from "../components/DiffPanel";
import { DishCard } from "../components/DishCard";
import { DishEditModal } from "../components/DishEditModal";
import { SectionBanner } from "../components/SectionBanner";
import { ApiError } from "../lib/apiClient";
import { activateMenu, deleteDish, fetchActiveMenu, getMenu, patchDish, setAvailability, setWhatsapp, uploadMenu } from "../lib/menuApi";
import { toast } from "../components/Toaster";
import type { DishOut, MenuWithDiffOut } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import { UnifiedMenuPanel } from "../components/UnifiedMenuPanel";
import s from "./MenuManagerScreen.module.css";

export function MenuManagerScreen({ initialMenuId }: { initialMenuId?: number }) {
  const [dishes, setDishes] = useState<DishOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<MenuWithDiffOut | null>(null);
  const [activeMenuId, setActiveMenuId] = useState<number | null>(initialMenuId ?? null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<DishOut | "new" | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);
  const [overId, setOverId] = useState<number | null>(null);
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

  // Drop the dragged dish onto a target within the SAME category, then renumber
  // so visual order == ascending dish number (Mutton dragged to top becomes #1).
  function onDropDish(items: DishOut[], targetId: number) {
    const draggedId = dragId;
    setDragId(null);
    setOverId(null);
    if (draggedId === null || draggedId === targetId || activeMenuId === null) return;

    const ids = items.map((d) => d.id);
    const from = ids.indexOf(draggedId);
    const to = ids.indexOf(targetId);
    if (from === -1 || to === -1) return; // dragged from a different category — ignore

    const reordered = [...items];
    const [moved] = reordered.splice(from, 1);
    reordered.splice(to, 0, moved);

    // The category's own number set, kept intact and reassigned by new position.
    const numbers = items.map((d) => d.dish_number ?? 0).sort((a, b) => a - b);

    // Optimistic: update numbers locally so the grid re-sorts instantly.
    const newNums = new Map<number, number>();
    reordered.forEach((d, i) => newNums.set(d.id, numbers[i]));
    setDishes((prev) =>
      prev.map((d) => (newNums.has(d.id) ? { ...d, dish_number: newNums.get(d.id)! } : d)),
    );

    void persistRenumber(reordered, numbers);
  }

  async function persistRenumber(reordered: DishOut[], numbers: number[]) {
    if (activeMenuId === null) return;
    const maxGlobal = Math.max(0, ...dishes.map((d) => d.dish_number ?? 0));
    try {
      // Phase 1: park every dish on an unused temp number to free the originals,
      // so phase 2 can assign final numbers without hitting the uniqueness check.
      for (let i = 0; i < reordered.length; i++) {
        await patchDish(activeMenuId, reordered[i].id, { dish_number: maxGlobal + 1 + i });
      }
      // Phase 2: assign the real numbers in the new order.
      for (let i = 0; i < reordered.length; i++) {
        await patchDish(activeMenuId, reordered[i].id, { dish_number: numbers[i] });
      }
    } catch {
      setError("Failed to reorder dishes.");
    } finally {
      reloadDishes();
    }
  }

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
    try {
      const result = await uploadMenu(Array.from(files));
      setPending(result);
    } catch {
      setError("Menu upload failed.");
    }
  }

  async function onConfirm() {
    if (!pending) return;
    await activateMenu(pending.id);
    setActiveMenuId(pending.id);
    setPending(null);
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

  // Drag-reorder only when a full category is shown (filters would hide siblings
  // and corrupt the renumbering).
  const canReorder = search.trim() === "" && availFilter === "all";

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
      <div className={s.screen}>
        <SectionBanner tone="info">New menu parsed. Review and confirm before activating.</SectionBanner>
        {pending.diff_vs_active ? <DiffPanel diff={pending.diff_vs_active} /> : <p>No diff.</p>}
        <div className={s.actions}>
          <Button onClick={onConfirm} disabled={hasErrors}>Confirm &amp; Activate</Button>
          <Button variant="ghost" onClick={() => setPending(null)}>Discard</Button>
          {hasErrors && <span className={s.blocked}>Resolve extraction errors before activating.</span>}
        </div>
      </div>
    );
  }

  return (
    <div className={s.screen}>
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
            {dishes.length > 0 && activeMenuId !== null && (
              <Button variant="ghost" onClick={() => setEditing("new")}>+ Add dish</Button>
            )}
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

          {canReorder && grouped.length > 0 && (
            <div className={s.reorderHint}>
              Drag dishes within a category to reorder. Tap “Available” to mark a dish unavailable (and tap again to bring it back).
            </div>
          )}

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
                  <div
                    key={d.id}
                    className={`${s.dragItem} ${canReorder ? s.draggable : ""} ${dragId === d.id ? s.dragging : ""} ${overId === d.id && dragId !== d.id ? s.dragOver : ""}`}
                    draggable={canReorder && items.length > 1}
                    onDragStart={canReorder ? () => setDragId(d.id) : undefined}
                    onDragEnter={canReorder ? () => setOverId(d.id) : undefined}
                    onDragOver={canReorder ? (e) => e.preventDefault() : undefined}
                    onDrop={canReorder ? () => onDropDish(items, d.id) : undefined}
                    onDragEnd={() => { setDragId(null); setOverId(null); }}
                  >
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
          onSaved={reloadDishes}
        />
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
