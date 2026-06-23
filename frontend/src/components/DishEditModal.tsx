import { useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
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
  // Serving-size variants (e.g. 1 serve / 4 serve), each with its own price. Empty
  // = flat dish priced at the base price above.
  const [variants, setVariants] = useState<{ name: string; price_aed: string }[]>(
    (d?.variants ?? []).map((v) => ({ name: v.name, price_aed: v.price_aed })),
  );

  function setVariant(i: number, patch: Partial<{ name: string; price_aed: string }>) {
    setVariants((vs) => vs.map((v, idx) => (idx === i ? { ...v, ...patch } : v)));
  }
  function addVariant() {
    setVariants((vs) => [...vs, { name: "", price_aed: "" }]);
  }
  function removeVariant(i: number) {
    setVariants((vs) => vs.filter((_, idx) => idx !== i));
  }

  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Full dropdown list: presets + any categories already in the menu + this
  // dish's current category (so an unusual existing value isn't lost).
  const categoryOptions = Array.from(
    new Set([...PRESET_CATEGORIES, ...categories, ...(category ? [category] : [])]),
  );

  // A serving size of 1 (or "single") is just the base price above — it doesn't
  // belong in the variants list, which is for bigger/sharing portions only.
  function servesTooSmall(vName: string): boolean {
    const n = vName.trim().toLowerCase();
    if (["1", "single", "one", "single serve", "1 serve"].includes(n)) return true;
    const m = n.match(/^(\d+)/);
    return m !== null && Number(m[1]) <= 1;
  }
  // Every variant row must be fully filled (name + positive price, 2+ servings)
  // before save — mirrors the backend activation guard so the manager fixes it here.
  const variantsValid = variants.every(
    (v) =>
      v.name.trim() !== "" &&
      v.price_aed.trim() !== "" &&
      Number(v.price_aed) > 0 &&
      !servesTooSmall(v.name),
  );
  const canSave = name.trim() !== "" && price.trim() !== "" && variantsValid && !busy;

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
      variants: variants.map((v) => ({ name: v.name.trim(), price_aed: v.price_aed.trim() })),
    };
    try {
      if (isNew) {
        await addDish(menuId, body);
        toast(`“${body.name}” added to the menu.`);
      } else {
        await patchDish(menuId, d!.id, body);
        toast(`“${body.name}” updated.`);
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
      toast(`“${d.name}” deleted.`);
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
          <h2 className={s.title}>{isNew ? "Add dish" : `Edit — ${d?.name}`}</h2>
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
              <span className={s.label}>Price (AED) — single serve *</span>
              <input
                className={s.input}
                type="number"
                step="0.01"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="20.00"
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

          <div className={s.variants}>
            <div className={s.variantsHead}>
              <span className={s.label}>Serving sizes (2+ only)</span>
              <span className={s.hint}>
                Optional — bigger portions only, e.g. 2 serve / Family. The single
                serve is the price above.
              </span>
            </div>
            {variants.map((v, i) => (
              <div className={s.variantRow} key={i}>
                <input
                  className={`${s.input} ${s.variantName}`}
                  value={v.name}
                  onChange={(e) => setVariant(i, { name: e.target.value })}
                  placeholder="4 serve"
                  aria-label={`Serving size ${i + 1} name`}
                />
                <input
                  className={`${s.input} ${s.variantPrice}`}
                  type="number"
                  step="0.01"
                  value={v.price_aed}
                  onChange={(e) => setVariant(i, { price_aed: e.target.value })}
                  placeholder="AED"
                  aria-label={`Serving size ${i + 1} price`}
                />
                <button
                  type="button"
                  className={s.variantRemove}
                  onClick={() => removeVariant(i)}
                  aria-label={`Remove serving size ${i + 1}`}
                >
                  ×
                </button>
              </div>
            ))}
            {variants.some((v) => servesTooSmall(v.name)) && (
              <span className={s.hint} style={{ color: "#b02a2a" }}>
                A single serve is the base price above — serving sizes must be 2 or more.
              </span>
            )}
            <button type="button" className={s.addVariant} onClick={addVariant}>
              + Add serving size
            </button>
          </div>
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
