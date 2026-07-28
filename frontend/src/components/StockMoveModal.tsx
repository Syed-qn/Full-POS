import { useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { createBatch, recordStockCount, restockIngredient, wasteIngredient } from "../lib/inventoryApi";
import type { IngredientOut } from "../lib/types";
import s from "./DishEditModal.module.css";
import t from "./StockMoveModal.module.css";

export type StockAction = "restock" | "waste" | "count" | "batch";

const ACTIONS: Array<{ id: StockAction; label: string; hint: string; verb: string }> = [
  { id: "restock", label: "Restock", hint: "Add stock you received.", verb: "Add stock" },
  { id: "waste", label: "Waste", hint: "Record stock that was lost.", verb: "Log waste" },
  {
    id: "count",
    label: "Count",
    hint: "Count without looking at the figure on screen, then enter what you found.",
    verb: "Save count",
  },
  { id: "batch", label: "Batch", hint: "Receive a dated batch, consumed earliest first.", verb: "Receive batch" },
];

/**
 * One stock move.
 *
 * This replaces a permanent five field grid plus four buttons that sat above
 * the stock table. Every field for every action was on screen at once, so the
 * expiry date was visible while restocking and the waste reason was visible
 * while counting. Here you pick the action first and only its own fields
 * appear.
 *
 * Reuses the shared modal stylesheet so it matches every other dialog.
 */
export function StockMoveModal({
  ingredients,
  initialIngredientId,
  initialAction = "restock",
  onClose,
  onDone,
  onActionChange,
}: {
  ingredients: IngredientOut[];
  initialIngredientId?: number | "";
  initialAction?: StockAction;
  onClose: () => void;
  onDone: (message: string) => void;
  /** The screen behind needs this: it hides the recorded stock figures while a
   *  count is in progress, and only the dialog knows which tab is open. */
  onActionChange?: (action: StockAction) => void;
}) {
  const [action, setAction] = useState<StockAction>(initialAction);
  const [ingredientId, setIngredientId] = useState<number | "">(
    initialIngredientId ?? ingredients[0]?.id ?? "",
  );
  const [quantity, setQuantity] = useState("1.000");
  const [reasonType, setReasonType] = useState<
    "wastage" | "spoilage" | "theft" | "over_portion" | "other"
  >("spoilage");
  const [reason, setReason] = useState("");
  // Why a count differed. Standard inventory reason codes — a count that
  // records the new number but not the cause is a changed figure, not an
  // audit trail.
  const [countReason, setCountReason] = useState("");
  const [expiry, setExpiry] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const qtyRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    qtyRef.current?.focus();
    qtyRef.current?.select();
  }, []);

  const current = ACTIONS.find((a) => a.id === action) ?? ACTIONS[0];
  const unit = ingredients.find((i) => i.id === Number(ingredientId))?.unit ?? "";
  const canSave =
    ingredientId !== "" && quantity.trim() !== "" && !busy && (action !== "batch" || expiry !== "");

  async function save() {
    if (!canSave) return;
    const id = Number(ingredientId);
    setBusy(true);
    setError(null);
    try {
      if (action === "restock") {
        await restockIngredient(id, { quantity });
        onDone("Stock restocked.");
      } else if (action === "waste") {
        await wasteIngredient(id, {
          quantity,
          reason: reason || undefined,
          reason_type: reasonType,
        });
        onDone(`${reasonType} logged.`);
      } else if (action === "count") {
        const result = await recordStockCount(id, {
          counted_qty: quantity,
          reason_code: countReason || null,
          reason: reason || null,
        });
        const value = result.variance_value_aed;
        // Say what it cost, not only how many kilos moved. The money is the
        // part that tells you whether this matters.
        const money =
          value != null && Number(value) !== 0
            ? ` (${Number(value) < 0 ? "-" : "+"}AED ${Math.abs(Number(value)).toFixed(2)})`
            : "";
        onDone(
          result.flagged
            ? `Count saved. Variance ${result.variance}${money} — over tolerance, flagged for review.`
            : `Count saved. Variance ${result.variance}${money}`,
        );
      } else {
        await createBatch(id, { qty: quantity, expiry_date: expiry });
        onDone("Batch received.");
      }
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stock operation failed.");
      setBusy(false);
    }
  }

  return (
    <div className={s.overlay} onClick={busy ? undefined : onClose}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-label="Stock move"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={s.header}>
          <h2 className={s.title}>Stock move</h2>
          <button className={s.close} onClick={onClose} aria-label="Close" disabled={busy}>
            ×
          </button>
        </div>

        {error && <div className={s.error}>{error}</div>}

        <div className={s.body}>
          <div className={t.tabs} role="tablist" aria-label="Stock action">
            {ACTIONS.map((a) => (
              <button
                key={a.id}
                type="button"
                role="tab"
                aria-selected={a.id === action}
                className={`${t.tab} ${a.id === action ? t.tabActive : ""}`}
                onClick={() => {
                  setAction(a.id);
                  onActionChange?.(a.id);
                }}
                disabled={busy}
              >
                {a.label}
              </button>
            ))}
          </div>
          <p className={t.hint}>{current.hint}</p>

          <label className={s.field}>
            <span className={s.label}>Ingredient</span>
            <select
              aria-label="Ops ingredient"
              className={s.input}
              value={ingredientId}
              onChange={(e) => setIngredientId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Select...</option>
              {ingredients.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.name}
                </option>
              ))}
            </select>
          </label>

          <label className={s.field}>
            <span className={s.label}>
              {action === "count" ? "Counted quantity" : "Quantity"}
              {unit ? ` (${unit})` : ""}
            </span>
            <input
              ref={qtyRef}
              aria-label="Ops quantity"
              className={s.input}
              inputMode="decimal"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && action !== "batch") void save();
              }}
            />
          </label>

          {/* Only the fields the chosen action actually uses. */}
          {action === "waste" && (
            <div className={s.row}>
              <label className={s.field}>
                <span className={s.label}>Reason type</span>
                <select
                  aria-label="Waste reason type"
                  className={s.input}
                  value={reasonType}
                  onChange={(e) => setReasonType(e.target.value as typeof reasonType)}
                >
                  <option value="spoilage">Spoilage</option>
                  <option value="wastage">Wastage</option>
                  <option value="theft">Theft</option>
                  <option value="over_portion">Over portion</option>
                  <option value="other">Other</option>
                </select>
              </label>
              <label className={s.field}>
                <span className={s.label}>Note</span>
                <input
                  aria-label="Ops reason"
                  className={s.input}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Optional detail"
                />
              </label>
            </div>
          )}

          {action === "count" && (
            <div className={s.row}>
              <label className={s.field}>
                <span className={s.label}>Reason for the difference</span>
                <select
                  aria-label="Count reason"
                  className={s.input}
                  value={countReason}
                  onChange={(e) => setCountReason(e.target.value)}
                >
                  <option value="">Not stated</option>
                  <option value="count_error">Previous figure was wrong</option>
                  <option value="damage">Damaged</option>
                  <option value="spoilage">Spoiled</option>
                  <option value="shrinkage">Unexplained loss</option>
                  <option value="transfer_variance">Moved to or from elsewhere</option>
                  <option value="system_correction">Fixing a data entry mistake</option>
                  <option value="other">Other</option>
                </select>
              </label>
              <label className={s.field}>
                <span className={s.label}>Note</span>
                <input
                  aria-label="Count note"
                  className={s.input}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Optional detail"
                />
              </label>
            </div>
          )}

          {action === "batch" && (
            <label className={s.field}>
              <span className={s.label}>Expiry date</span>
              <input
                type="date"
                aria-label="Batch expiry"
                className={s.input}
                value={expiry}
                onChange={(e) => setExpiry(e.target.value)}
              />
            </label>
          )}
        </div>

        <div className={s.footer}>
          <div className={s.footerRight}>
            <Button size="md" variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button size="md" onClick={() => void save()} disabled={!canSave}>
              {busy ? "Saving..." : current.verb}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
