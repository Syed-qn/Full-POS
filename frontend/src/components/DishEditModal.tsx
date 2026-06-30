import { useRef, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import { addDish, deleteDish, patchDish, uploadDishImage } from "../lib/menuApi";
import { ApiError } from "../lib/apiClient";
import type { DishOut } from "../lib/types";
import s from "./DishEditModal.module.css";

const DISH_IMAGE_MAX_BYTES = 5 * 1024 * 1024;

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

/** Categories whose variants are SIZES (Large/Small), not bigger food portions.
 *  Mirrors the bot's _DRINK_CATEGORY_HINTS so the editor matches the ordering flow. */
const DRINK_CATEGORY_HINTS = [
  "drink", "beverage", "juice", "soda", "water", "tea", "coffee", "shake",
  "smoothie", "mocktail", "lassi", "cola", "mint",
];
function isDrinkCategory(cat: string): boolean {
  const c = cat.trim().toLowerCase();
  return DRINK_CATEGORY_HINTS.some((h) => c.includes(h));
}

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
  // ── Meta catalogue product fields ──────────────────────────────────────────
  // Only the fields a restaurant actually sets are shown: the Photo (Meta requires
  // an image) and an optional Sale price. The rest (brand=restaurant name,
  // condition=new, status=active, content id=auto, FB category) are filled
  // automatically on the server, so they're not surfaced here.
  const [imageUrl, setImageUrl] = useState(d?.image_url ?? "");
  const [uploadingImage, setUploadingImage] = useState(false);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [salePrice, setSalePrice] = useState(d?.sale_price_aed ?? "");

  async function onPickImage(file: File | undefined) {
    if (!file) return;
    if (!["image/jpeg", "image/png"].includes(file.type)) {
      toast("Dish photo must be a JPG or PNG.", "error");
      return;
    }
    if (file.size > DISH_IMAGE_MAX_BYTES) {
      toast("Image is too large (max 5 MB).", "error");
      return;
    }
    setUploadingImage(true);
    try {
      const { url } = await uploadDishImage(file);
      setImageUrl(url);
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Image upload failed.", "error");
    } finally {
      setUploadingImage(false);
      if (imageInputRef.current) imageInputRef.current.value = "";
    }
  }
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

  // Drinks pick a SIZE (Large/Small) — anything goes; food serving sizes are bigger
  // portions only, so a "1 serve" there is just the base price and is rejected.
  const isDrink = isDrinkCategory(category);
  function servesTooSmall(vName: string): boolean {
    if (isDrink) return false; // drink sizes (Large/Small) have no 2+ rule
    const n = vName.trim().toLowerCase();
    if (["1", "single", "one", "single serve", "1 serve"].includes(n)) return true;
    const m = n.match(/^(\d+)/);
    return m !== null && Number(m[1]) <= 1;
  }
  // Every variant row must be fully filled (name + positive price; food also 2+
  // servings) before save — mirrors the backend activation guard.
  const variantsValid = variants.every(
    (v) =>
      v.name.trim() !== "" &&
      v.price_aed.trim() !== "" &&
      Number(v.price_aed) > 0 &&
      !servesTooSmall(v.name),
  );
  // Meta REQUIRES a product image, so a NEW dish must carry a photo before it can go
  // live on WhatsApp. Existing dishes keep working (placeholder fallback on the server).
  const imageOk = !isNew || imageUrl.trim() !== "";
  // Sale price, when set, must be a positive number below the base price.
  const saleOk =
    salePrice.trim() === "" ||
    (Number(salePrice) > 0 && (price.trim() === "" || Number(salePrice) < Number(price)));
  const canSave =
    name.trim() !== "" &&
    price.trim() !== "" &&
    variantsValid &&
    imageOk &&
    saleOk &&
    !uploadingImage &&
    !busy;

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
      // Meta catalogue product fields (rest are auto-filled on the server).
      image_url: imageUrl.trim() || null,
      sale_price_aed: salePrice.trim() || null,
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

          <div className={s.field}>
            <span className={s.label}>Photo {isNew ? "*" : ""}</span>
            <div className={s.imageRow}>
              <div className={s.imageThumb}>
                {imageUrl ? (
                  <img src={imageUrl} alt="" />
                ) : (
                  <span className={s.imagePh}>No photo</span>
                )}
              </div>
              <div className={s.imageActions}>
                <input
                  ref={imageInputRef}
                  data-testid="dish-image-input"
                  type="file"
                  accept="image/jpeg,image/png"
                  style={{ display: "none" }}
                  onChange={(e) => onPickImage(e.target.files?.[0] ?? undefined)}
                />
                <Button
                  variant="ghost"
                  onClick={() => imageInputRef.current?.click()}
                  disabled={uploadingImage}
                >
                  {uploadingImage ? "Uploading…" : imageUrl ? "Replace photo" : "Upload photo"}
                </Button>
                {imageUrl && (
                  <button
                    type="button"
                    className={s.imageRemove}
                    onClick={() => setImageUrl("")}
                  >
                    Remove
                  </button>
                )}
                <span className={s.hint}>
                  JPG or PNG, at least 500×500. Required to publish on WhatsApp.
                </span>
              </div>
            </div>
          </div>

          <div className={s.row}>
            <label className={s.field}>
              <span className={s.label}>{isDrink ? "Base price (AED) *" : "Price (AED) — single serve *"}</span>
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

          <label className={s.field}>
            <span className={s.label}>Sale price (AED)</span>
            <input
              className={s.input}
              type="number"
              step="0.01"
              value={salePrice}
              onChange={(e) => setSalePrice(e.target.value)}
              placeholder="Optional — discounted price shown on WhatsApp"
              aria-label="Sale price"
            />
            {!saleOk && (
              <span className={s.hint} style={{ color: "#b02a2a" }}>
                Sale price must be a positive number below the base price.
              </span>
            )}
          </label>

          <div className={s.variants}>
            <div className={s.variantsHead}>
              <span className={s.label}>{isDrink ? "Sizes" : "Serving sizes (2+ only)"}</span>
              <span className={s.hint}>
                {isDrink
                  ? "Optional — e.g. Large / Small, each with its own price. The bot asks the customer which size."
                  : "Optional — bigger portions only, e.g. 2 serve / Family. The single serve is the price above."}
              </span>
            </div>
            {variants.map((v, i) => (
              <div className={s.variantRow} key={i}>
                <input
                  className={`${s.input} ${s.variantName}`}
                  value={v.name}
                  onChange={(e) => setVariant(i, { name: e.target.value })}
                  placeholder={isDrink ? "Large" : "4 serve"}
                  aria-label={isDrink ? `Size ${i + 1} name` : `Serving size ${i + 1} name`}
                />
                <input
                  className={`${s.input} ${s.variantPrice}`}
                  type="number"
                  step="0.01"
                  value={v.price_aed}
                  onChange={(e) => setVariant(i, { price_aed: e.target.value })}
                  placeholder="AED"
                  aria-label={isDrink ? `Size ${i + 1} price` : `Serving size ${i + 1} price`}
                />
                <button
                  type="button"
                  className={s.variantRemove}
                  onClick={() => removeVariant(i)}
                  aria-label={isDrink ? `Remove size ${i + 1}` : `Remove serving size ${i + 1}`}
                >
                  ×
                </button>
              </div>
            ))}
            {!isDrink && variants.some((v) => servesTooSmall(v.name)) && (
              <span className={s.hint} style={{ color: "#b02a2a" }}>
                A single serve is the base price above — serving sizes must be 2 or more.
              </span>
            )}
            <button type="button" className={s.addVariant} onClick={addVariant}>
              {isDrink ? "+ Add size" : "+ Add serving size"}
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
