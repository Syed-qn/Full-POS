import { useEffect, useRef, useState } from "react";
import { Button } from "./Button";
import { createPurchaseOrder, createVendor } from "../lib/inventoryApi";
import type { IngredientOut, PurchaseOrderOut, VendorOut } from "../lib/types";
import s from "./DishEditModal.module.css";

/**
 * Add a supplier.
 *
 * Split out of the inventory screen, where the vendor fields sat permanently
 * beside the purchase order fields even though a supplier is added once and a
 * purchase order is raised every week.
 */
export function VendorAddModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (vendor: VendorOut) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  const canSave = name.trim() !== "" && !busy;

  async function save() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    try {
      const vendor = await createVendor({ name: name.trim(), phone: phone.trim() || null });
      onCreated(vendor);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the vendor.");
      setBusy(false);
    }
  }

  return (
    <div className={s.overlay} onClick={busy ? undefined : onClose}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-label="New vendor"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={s.header}>
          <h2 className={s.title}>New vendor</h2>
          <button className={s.close} onClick={onClose} aria-label="Close" disabled={busy}>
            ×
          </button>
        </div>

        {error && <div className={s.error}>{error}</div>}

        <div className={s.body}>
          <label className={s.field}>
            <span className={s.label}>Vendor name</span>
            <input
              ref={nameRef}
              aria-label="Vendor name"
              className={s.input}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Fresh Produce Trading"
            />
          </label>
          <label className={s.field}>
            <span className={s.label}>Phone</span>
            <input
              aria-label="Vendor phone"
              className={s.input}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="Optional"
              onKeyDown={(e) => {
                if (e.key === "Enter") void save();
              }}
            />
          </label>
        </div>

        <div className={s.footer}>
          <div className={s.footerRight}>
            <Button size="md" variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button size="md" onClick={() => void save()} disabled={!canSave}>
              {busy ? "Adding..." : "Add vendor"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Raise a single line purchase order against a supplier.
 */
export function PurchaseOrderModal({
  vendors,
  ingredients,
  initialVendorId,
  initialIngredientId,
  onClose,
  onCreated,
}: {
  vendors: VendorOut[];
  ingredients: IngredientOut[];
  initialVendorId?: number | "";
  initialIngredientId?: number | "";
  onClose: () => void;
  onCreated: (po: PurchaseOrderOut) => void;
}) {
  const [vendorId, setVendorId] = useState<number | "">(initialVendorId ?? vendors[0]?.id ?? "");
  const [ingredientId, setIngredientId] = useState<number | "">(
    initialIngredientId ?? ingredients[0]?.id ?? "",
  );
  const [quantity, setQuantity] = useState("5.000");
  const [cost, setCost] = useState("1.0000");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSave = vendorId !== "" && ingredientId !== "" && !busy;

  async function save() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    try {
      const po = await createPurchaseOrder({
        vendor_id: Number(vendorId),
        lines: [
          {
            ingredient_id: Number(ingredientId),
            qty_ordered: quantity,
            unit_cost_aed: cost,
          },
        ],
      });
      onCreated(po);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the purchase order.");
      setBusy(false);
    }
  }

  return (
    <div className={s.overlay} onClick={busy ? undefined : onClose}>
      <div
        className={s.modal}
        role="dialog"
        aria-modal="true"
        aria-label="New purchase order"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={s.header}>
          <h2 className={s.title}>New purchase order</h2>
          <button className={s.close} onClick={onClose} aria-label="Close" disabled={busy}>
            ×
          </button>
        </div>

        {error && <div className={s.error}>{error}</div>}

        <div className={s.body}>
          {vendors.length === 0 && (
            <p className={s.label}>Add a vendor first, then raise the order against it.</p>
          )}
          <label className={s.field}>
            <span className={s.label}>Vendor</span>
            <select
              aria-label="PO vendor"
              className={s.input}
              value={vendorId}
              onChange={(e) => setVendorId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Select...</option>
              {vendors.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </label>
          <label className={s.field}>
            <span className={s.label}>Ingredient</span>
            <select
              aria-label="PO ingredient"
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
          <div className={s.row}>
            <label className={s.field}>
              <span className={s.label}>Quantity ordered</span>
              <input
                aria-label="PO qty"
                className={s.input}
                inputMode="decimal"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
            </label>
            <label className={s.field}>
              <span className={s.label}>Unit cost (AED)</span>
              <input
                aria-label="PO cost"
                className={s.input}
                inputMode="decimal"
                value={cost}
                onChange={(e) => setCost(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void save();
                }}
              />
            </label>
          </div>
        </div>

        <div className={s.footer}>
          <div className={s.footerRight}>
            <Button size="md" variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button size="md" onClick={() => void save()} disabled={!canSave}>
              {busy ? "Creating..." : "Create order"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
