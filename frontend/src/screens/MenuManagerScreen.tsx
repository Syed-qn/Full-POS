import { useEffect, useRef, useState } from "react";
import { Button } from "../components/Button";
import { DiffPanel } from "../components/DiffPanel";
import { DishCard } from "../components/DishCard";
import { SectionBanner } from "../components/SectionBanner";
import { activateMenu, fetchActiveMenu, getMenu, setAvailability, uploadMenu } from "../lib/menuApi";
import type { DishOut, MenuWithDiffOut } from "../lib/types";
import s from "./MenuManagerScreen.module.css";

export function MenuManagerScreen({ initialMenuId }: { initialMenuId?: number }) {
  const [dishes, setDishes] = useState<DishOut[]>([]);
  const [pending, setPending] = useState<MenuWithDiffOut | null>(null);
  const [activeMenuId, setActiveMenuId] = useState<number | null>(initialMenuId ?? null);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

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
      <div className={s.bar}>
        <span className="label-upper">Menu</span>
        <input
          ref={fileRef}
          type="file"
          multiple
          hidden
          onChange={(e) => onUpload(e.target.files)}
          data-testid="menu-upload"
        />
        <Button onClick={() => fileRef.current?.click()}>Upload new menu</Button>
      </div>
      {dishes.length === 0 ? (
        <div className={s.empty}>Upload your first menu to get started.</div>
      ) : (
        <div className={s.grid}>
          {dishes.map((d) => (
            <DishCard key={d.id} dish={d} onToggle={onToggle} />
          ))}
        </div>
      )}
    </div>
  );
}
