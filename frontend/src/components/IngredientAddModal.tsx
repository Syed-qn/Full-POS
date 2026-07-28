import { useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { createIngredient } from "../lib/inventoryApi";
import type { IngredientOut } from "../lib/types";
import s from "./DishEditModal.module.css";

/**
 * Add one ingredient.
 *
 * This was a permanent form sitting between the metrics and the stock tools,
 * so the six fields you fill in once per ingredient took up the space of the
 * table you read every day. Same fields, behind a button.
 *
 * Reuses the shared modal stylesheet so it matches every other add dialog
 * rather than growing its own look.
 */
export function IngredientAddModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (created: IngredientOut) => void;
}) {
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("kg");
  const [currentStock, setCurrentStock] = useState("");
  const [lowStock, setLowStock] = useState("");
  const [parLevel, setParLevel] = useState("");
  const [cost, setCost] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  // Name and unit are the only things an ingredient cannot exist without. The
  // rest are stock figures that are legitimately zero on day one, so requiring
  // them would just make people type zeros.
  const canSave = name.trim() !== "" && unit.trim() !== "" && !busy;

  async function save() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createIngredient({
        name: name.trim(),
        unit: unit.trim(),
        current_stock: currentStock,
        low_stock_threshold: lowStock,
        par_level: parLevel,
        cost_per_unit_aed: cost,
      });
      onCreated(created);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add the ingredient.");
      setBusy(false);
    }
  }

  return (
    <div className={s.overlay} onClick={busy ? undefined : onClose}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-label="New ingredient"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={s.header}>
          <h2 className={s.title}>New ingredient</h2>
          <button className={s.close} onClick={onClose} aria-label="Close" disabled={busy}>
            ×
          </button>
        </div>

        {error && <div className={s.error}>{error}</div>}

        <div className={s.body}>
          <div className={s.row}>
            <label className={s.field}>
              <span className={s.label}>Ingredient name</span>
              <input
                ref={nameRef}
                aria-label="Ingredient name"
                className={s.input}
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Basmati rice"
              />
            </label>
            <label className={s.field}>
              <span className={s.label}>Unit</span>
              <input
                aria-label="Unit"
                className={s.input}
                value={unit}
                onChange={(e) => setUnit(e.target.value)}
                placeholder="kg, litre, piece"
              />
            </label>
          </div>

          <div className={s.row}>
            <label className={s.field}>
              <span className={s.label}>Current stock</span>
              <input
                aria-label="Current stock"
                className={s.input}
                inputMode="decimal"
                value={currentStock}
                onChange={(e) => setCurrentStock(e.target.value)}
                placeholder="0"
              />
            </label>
            <label className={s.field}>
              <span className={s.label}>Cost per unit</span>
              <input
                aria-label="Cost per unit"
                className={s.input}
                inputMode="decimal"
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                placeholder="0.00"
              />
            </label>
          </div>

          <div className={s.row}>
            <label className={s.field}>
              <span className={s.label}>Low stock threshold</span>
              <input
                aria-label="Low stock threshold"
                className={s.input}
                inputMode="decimal"
                value={lowStock}
                onChange={(e) => setLowStock(e.target.value)}
                placeholder="Warn below this"
              />
            </label>
            <label className={s.field}>
              <span className={s.label}>Par level</span>
              <input
                aria-label="Par level"
                className={s.input}
                inputMode="decimal"
                value={parLevel}
                onChange={(e) => setParLevel(e.target.value)}
                placeholder="Top back up to this"
                onKeyDown={(e) => {
                  if (e.key === "Enter") void save();
                }}
              />
            </label>
          </div>
        </div>

        <div className={s.footer}>
          <div className={s.footerRight}>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void save()} disabled={!canSave}>
              {busy ? "Adding…" : "Add ingredient"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
