import { useState } from "react";
import { Button } from "./Button";
import { addDish, deleteDish, patchDish } from "../lib/menuApi";
import { ApiError } from "../lib/apiClient";
import type { DishOut } from "../lib/types";
import s from "./DishEditModal.module.css";

/** Standard restaurant menu categories offered in the dropdown. */
const PRESET_CATEGORIES = [
  "Starters",
  "Appetizers",
  "Soups",
  "Salads",
  "Biryani",
  "Rice",
  "Breads",
  "Curries",
  "Tandoori",
  "Grills",
  "Seafood",
  "Mains",
  "Sides",
  "Desserts",
  "Drinks",
  "Other",
];

interface Props {
  menuId: number;
  /** Existing dish to edit, or "new" to create one. */
  dish: DishOut | "new";
  /** Categories already used in this menu, merged into the dropdown. */
  categories: string[];
  /** Next free dish number, auto-assigned to new dishes (manager never types it). */
  nextNumber: number;
  onClose: () => void;
  /** Called after a successful save/delete so the parent can reload. */
  onSaved: () => void;
}

export function DishEditModal({ menuId, dish, categories, nextNumber, onClose, onSaved }: Props) {
  const isNew = dish === "new";
  const d = isNew ? null : dish;

  // Dish number is assigned automatically — managers never enter it.
  const dishNumber = isNew ? nextNumber : (d?.dish_number ?? nextNumber);
  const [name, setName] = useState(d?.name ?? "");
  const [price, setPrice] = useState(d?.price_aed ?? "");
  const [category, setCategory] = useState(d?.category ?? "");
  const [description, setDescription] = useState(d?.description ?? "");

  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Full dropdown list: presets + any categories already in the menu + this
  // dish's current category (so an unusual existing value isn't lost).
  const categoryOptions = Array.from(
    new Set([...PRESET_CATEGORIES, ...categories, ...(category ? [category] : [])]),
  );

  const canSave = name.trim() !== "" && price.trim() !== "" && !busy;

  async function onSave() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    const body = {
      dish_number: dishNumber,
      name: name.trim(),
      price_aed: price.trim(),
      category: category.trim() || null,
      description: description.trim() || null,
    };
    try {
      if (isNew) {
        await addDish(menuId, body);
      } else {
        await patchDish(menuId, d!.id, body);
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to save dish.");
      setBusy(false);
    }
  }

  async function onDelete() {
    if (isNew || !d) return;
    setBusy(true);
    setError(null);
    try {
      await deleteDish(menuId, d.id);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to delete dish.");
      setBusy(false);
    }
  }

  return (
    <div className={s.overlay} onClick={onClose}>
      <div className={s.modal} onClick={(e) => e.stopPropagation()}>
        <div className={s.header}>
          <h2 className={s.title}>{isNew ? `Add dish #${dishNumber}` : `Edit #${d?.dish_number} — ${d?.name}`}</h2>
          <button className={s.close} onClick={onClose} aria-label="Close">×</button>
        </div>

        {error && <div className={s.error}>{error}</div>}

        <div className={s.body}>
          <label className={s.field}>
            <span className={s.label}>Name *</span>
            <input
              className={s.input}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Chicken Biryani"
              autoFocus
            />
          </label>

          <div className={s.row}>
            <label className={s.field}>
              <span className={s.label}>Price (AED) *</span>
              <input
                className={s.input}
                type="number"
                step="0.01"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="28.00"
              />
            </label>
            <label className={s.field}>
              <span className={s.label}>Category</span>
              <select
                className={s.input}
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              >
                <option value="">— Select category —</option>
                {categoryOptions.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </label>
          </div>

          <label className={s.field}>
            <span className={s.label}>Description</span>
            <textarea
              className={s.textarea}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Customer-facing description (max 3 lines, no price)"
              rows={3}
            />
          </label>
        </div>

        <div className={s.footer}>
          {!isNew && (
            confirmDelete ? (
              <span className={s.deleteConfirm}>
                Delete this dish?
                <button className={s.deleteYes} onClick={onDelete} disabled={busy}>Yes, delete</button>
                <button className={s.deleteNo} onClick={() => setConfirmDelete(false)} disabled={busy}>No</button>
              </span>
            ) : (
              <button className={s.deleteBtn} onClick={() => setConfirmDelete(true)} disabled={busy}>
                Delete
              </button>
            )
          )}
          <div className={s.footerRight}>
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button onClick={onSave} disabled={!canSave}>
              {busy ? "Saving…" : isNew ? "Add dish" : "Save changes"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
