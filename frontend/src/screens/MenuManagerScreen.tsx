import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../components/Button";
import { DiffPanel } from "../components/DiffPanel";
import { DishCard } from "../components/DishCard";
import { DishEditModal } from "../components/DishEditModal";
import { SectionBanner } from "../components/SectionBanner";
import { activateMenu, fetchActiveMenu, getMenu, patchDish, setAvailability, uploadMenu } from "../lib/menuApi";
import type { DishOut, MenuWithDiffOut } from "../lib/types";
import { PageHeader } from "../components/PageHeader";
import s from "./MenuManagerScreen.module.css";

export function MenuManagerScreen({ initialMenuId }: { initialMenuId?: number }) {
  const [dishes, setDishes] = useState<DishOut[]>([]);
  const [pending, setPending] = useState<MenuWithDiffOut | null>(null);
  const [activeMenuId, setActiveMenuId] = useState<number | null>(initialMenuId ?? null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<DishOut | "new" | null>(null);
  const [dragId, setDragId] = useState<number | null>(null);
  const [overId, setOverId] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  function reloadDishes() {
    if (activeMenuId !== null) {
      getMenu(activeMenuId).then((m) => setDishes(m.dishes)).catch(() => {});
    } else {
      fetchActiveMenu()
        .then((m) => {
          if (m) {
            setActiveMenuId(m.id);
            setDishes(m.dishes);
          }
        })
        .catch(() => {});
    }
  }

  useEffect(() => {
    if (pending !== null) return;
    if (activeMenuId !== null) {
      // Known menu id (after an upload+activate, or passed in): load its dishes.
      getMenu(activeMenuId).then((m) => setDishes(m.dishes)).catch(() => {});
    } else {
      // First mount with no id: discover the restaurant's active menu so the
      // current dishes show up instead of the empty "upload your first menu"
      // state. Without this the screen never loads an existing/seeded menu.
      fetchActiveMenu()
        .then((m) => {
          if (m) {
            setActiveMenuId(m.id);
            setDishes(m.dishes);
          }
        })
        .catch(() => {});
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

  async function onToggle(id: number, next: boolean) {
    setDishes((ds) => ds.map((d) => (d.id === id ? { ...d, is_available: next } : d)));
    try {
      await setAvailability(id, next);
    } catch {
      setDishes((ds) => ds.map((d) => (d.id === id ? { ...d, is_available: !next } : d)));
      setError("Failed to update availability.");
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

  const availableCount = dishes.filter((d) => d.is_available).length;

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
        <SectionBanner tone="info">New menu parsed — review and confirm before activating.</SectionBanner>
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
        subtitle="Manage your dishes and availability"
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
              <Button onClick={() => setEditing("new")}>+ Add dish</Button>
            )}
            {/* Upload new menu button hidden for now — re-enable when ready.
            <Button onClick={() => fileRef.current?.click()}>Upload new menu</Button> */}
          </>
        }
      />
      {dishes.length === 0 ? (
        <div className={s.empty}>Upload your first menu to get started.</div>
      ) : (
        <>
          <div className={s.stats}>
            <span className={s.stat}>
              <span className={s.statNum}>{dishes.length}</span> dishes
            </span>
            <span className={s.statDivider} />
            <span className={s.stat}>
              <span className={s.statDot} /> {availableCount} available
            </span>
            {availableCount < dishes.length && (
              <span className={s.stat}>
                <span className={`${s.statDot} ${s.statDotOff}`} /> {dishes.length - availableCount} unavailable
              </span>
            )}
            <span className={s.stat}>
              <span className={s.statNum}>{allCategories.length}</span> categories
            </span>
          </div>

          <div className={s.filterBar}>
            <input
              className={s.search}
              placeholder="Search dish name or #number"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
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

          {canReorder && grouped.length > 0 && (
            <div className={s.reorderHint}>
              Drag dishes within a category to reorder — numbers update automatically.
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
                    <DishCard dish={d} onToggle={onToggle} onEdit={setEditing} />
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
