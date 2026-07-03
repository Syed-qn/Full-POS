import { useMemo, useRef, useState } from "react";
import { Button } from "./Button";
import { toast } from "./Toaster";
import { deleteDish, patchDish, uploadDishImage } from "../lib/menuApi";
import { ApiError } from "../lib/apiClient";
import type { DishOut, MenuWithDiffOut } from "../lib/types";
import s from "./MenuReviewDialog.module.css";

const DISH_IMAGE_MAX_BYTES = 5 * 1024 * 1024;

/**
 * Post-upload menu review — a master/detail dialog styled like the Settings page.
 * Left: the extracted dishes grouped by category. Right: a pre-filled edit form
 * for the selected dish. Editing a field and saving writes back to that dish
 * (PATCH) so the manager can correct the extraction before activating.
 */
type Variant = { name: string; price_aed: string };

interface Props {
  menu: MenuWithDiffOut;
  onClose: () => void;
  onConfirm: () => void;
  confirming?: boolean;
  hasErrors?: boolean;
}

export function MenuReviewDialog({ menu, onClose, onConfirm, confirming = false, hasErrors = false }: Props) {
  // Local working copy so edits reflect in the left list immediately.
  const [dishes, setDishes] = useState<DishOut[]>(menu.dishes);
  const [selectedId, setSelectedId] = useState<number | null>(menu.dishes[0]?.id ?? null);

  const categories = useMemo(
    () => Array.from(new Set(dishes.map((d) => d.category ?? "Other"))).sort(),
    [dishes],
  );

  // Group left list by category, dish-number order within each.
  const grouped = useMemo(() => {
    const map = new Map<string, DishOut[]>();
    for (const d of dishes) {
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
  }, [dishes]);

  const selected = dishes.find((d) => d.id === selectedId) ?? null;
  // Ids with a delete in flight. A Set (not a single id) so several dishes can be
  // deleting at once — the live DELETE is slow (Meta unpublish + grounding), and a
  // single in-flight gate would block removing a second dish until the first finished.
  const [removingIds, setRemovingIds] = useState<Set<number>>(new Set());

  // Meta requires a product image. Dishes with no photo can't publish to the
  // WhatsApp catalogue, so we flag them and gate activation until they're set.
  const hasPhoto = (d: DishOut) => Boolean((d.image_url ?? "").trim());
  const missingPhotos = dishes.filter((d) => !hasPhoto(d)).length;

  function applyLocal(updated: DishOut) {
    setDishes((ds) => ds.map((d) => (d.id === updated.id ? updated : d)));
  }

  async function onRemove(id: number) {
    // Optimistic + concurrent: drop the row immediately (the × feels instant) and let
    // the slow live DELETE run in the background. Each delete is independent, so you
    // can remove a second dish without waiting for the first. Roll back only on error.
    const removed = dishes.find((d) => d.id === id);
    if (!removed || removingIds.has(id)) return;
    const remaining = dishes.filter((d) => d.id !== id);
    setDishes((cur) => cur.filter((d) => d.id !== id));
    if (selectedId === id) setSelectedId(remaining[0]?.id ?? null);
    setRemovingIds((s) => new Set(s).add(id));
    try {
      await deleteDish(menu.id, id);
      toast("Dish removed.");
    } catch (e) {
      // Re-insert the row (functional update so a concurrent delete isn't clobbered).
      setDishes((cur) => (cur.some((d) => d.id === id) ? cur : [...cur, removed]));
      toast(e instanceof ApiError ? e.detail : "Could not remove dish.", "error");
    } finally {
      setRemovingIds((s) => {
        const n = new Set(s);
        n.delete(id);
        return n;
      });
    }
  }

  return (
    <div className={s.overlay} onClick={onClose}>
      <div className={s.dialog} onClick={(e) => e.stopPropagation()}>
        <header className={s.header}>
          <div>
            <h2 className={s.title}>Review extracted menu</h2>
            <p className={s.sub}>
              {dishes.length} dishes across {categories.length} categories. Click a dish to edit, then activate.
            </p>
          </div>
          <button className={s.close} onClick={onClose} aria-label="Close">×</button>
        </header>

        <div className={s.body}>
          {/* LEFT — dish list */}
          <aside className={s.list}>
            {grouped.map(({ cat, items }) => (
              <div key={cat} className={s.listGroup}>
                <div className={s.listGroupHead}>
                  <span>{cat}</span>
                  <span className={s.listGroupCount}>{items.length}</span>
                </div>
                {items.map((d) => (
                  <div
                    key={d.id}
                    className={`${s.listItem} ${d.id === selectedId ? s.listItemActive : ""}`}
                  >
                    <button className={s.listItemMain} onClick={() => setSelectedId(d.id)}>
                      <span className={s.listItemName}>
                        {d.dish_number != null && <span className={s.listNum}>{d.dish_number}</span>}
                        {!hasPhoto(d) && (
                          <span className={s.noPhoto} title="No photo yet — needed to publish">📷</span>
                        )}
                        {d.name}
                      </span>
                      <span className={s.listItemPrice}>{d.price_aed ? `AED ${d.price_aed}` : "—"}</span>
                    </button>
                    <button
                      className={s.listItemRemove}
                      onClick={() => onRemove(d.id)}
                      disabled={removingIds.has(d.id)}
                      aria-label={`Remove ${d.name}`}
                      title="Remove dish"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            ))}
          </aside>

          {/* RIGHT — detail form */}
          <section className={s.detail}>
            {selected ? (
              <DishDetailForm
                key={selected.id}
                menuId={menu.id}
                dish={selected}
                categories={categories}
                onSaved={applyLocal}
              />
            ) : (
              <div className={s.detailEmpty}>Select a dish on the left to edit it.</div>
            )}
          </section>
        </div>

        <footer className={s.footer}>
          {hasErrors ? (
            <span className={s.blocked}>Resolve extraction errors before activating.</span>
          ) : missingPhotos > 0 ? (
            <span className={s.blocked}>
              📷 {missingPhotos} dish{missingPhotos === 1 ? "" : "es"} need a photo before publishing.
            </span>
          ) : null}
          <div className={s.footerRight}>
            <Button variant="ghost" onClick={onClose}>Discard</Button>
            <Button onClick={onConfirm} disabled={confirming || hasErrors || missingPhotos > 0}>
              {confirming ? "Activating…" : "Confirm & Activate"}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}

/** Pre-filled, editable form for one dish. Saves via PATCH and reports the
 *  updated dish up so the left list stays in sync. */
function DishDetailForm({
  menuId,
  dish,
  categories,
  onSaved,
}: {
  menuId: number;
  dish: DishOut;
  categories: string[];
  onSaved: (d: DishOut) => void;
}) {
  const [name, setName] = useState(dish.name ?? "");
  const [price, setPrice] = useState(dish.price_aed ?? "");
  const [category, setCategory] = useState(dish.category ?? "");
  const [description, setDescription] = useState(dish.description ?? "");
  const [salePrice, setSalePrice] = useState(dish.sale_price_aed ?? "");
  const [imageUrl, setImageUrl] = useState(dish.image_url ?? "");
  const [uploadingImage, setUploadingImage] = useState(false);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const [variants, setVariants] = useState<Variant[]>(
    (dish.variants ?? []).map((v) => ({ name: v.name, price_aed: v.price_aed })),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function setVariant(i: number, patch: Partial<Variant>) {
    setVariants((vs) => vs.map((v, idx) => (idx === i ? { ...v, ...patch } : v)));
  }

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
    let url: string;
    try {
      ({ url } = await uploadDishImage(file));
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Image upload failed.", "error");
      setUploadingImage(false);
      if (imageInputRef.current) imageInputRef.current.value = "";
      return;
    }
    setUploadingImage(false);
    if (imageInputRef.current) imageInputRef.current.value = "";
    setImageUrl(url);
    // Update the shared list IMMEDIATELY (before the persist round-trip) so switching
    // dishes and coming back still shows the photo — a remount re-reads dish.image_url
    // from the parent, and this is what puts it there. Doing it before awaiting patchDish
    // means a slow/hanging save can't strand the UI without the image.
    onSaved({ ...dish, image_url: url });
    toast("Photo added.");
    // Persist to the DB (best-effort). The file is already stored server-side; this links
    // it to the dish so it survives a reload and counts toward the activation gate.
    try {
      await patchDish(menuId, dish.id, { image_url: url });
    } catch (err) {
      toast(err instanceof ApiError ? err.detail : "Couldn't save the photo — click Save.", "error");
    }
  }

  const dirty =
    name !== (dish.name ?? "") ||
    price !== (dish.price_aed ?? "") ||
    category !== (dish.category ?? "") ||
    description !== (dish.description ?? "") ||
    salePrice !== (dish.sale_price_aed ?? "") ||
    imageUrl !== (dish.image_url ?? "") ||
    JSON.stringify(variants) !==
      JSON.stringify((dish.variants ?? []).map((v) => ({ name: v.name, price_aed: v.price_aed })));

  const canSave = name.trim() !== "" && price.trim() !== "" && dirty && !busy;

  async function onSave() {
    if (!canSave) return;
    setBusy(true);
    setError(null);
    const body = {
      dish_number: dish.dish_number ?? undefined,
      name: name.trim(),
      price_aed: price.trim(),
      category: category.trim() || null,
      description: description.trim() || null,
      sale_price_aed: salePrice.trim() || null,
      image_url: imageUrl.trim() || null,
      variants: variants.map((v) => ({ name: v.name.trim(), price_aed: v.price_aed.trim() })),
    };
    try {
      await patchDish(menuId, dish.id, body);
      onSaved({
        ...dish,
        name: body.name,
        price_aed: body.price_aed,
        category: body.category,
        description: body.description,
        sale_price_aed: body.sale_price_aed,
        image_url: body.image_url,
        variants: body.variants.map((v) => ({ name: v.name, price_aed: v.price_aed, dish_number: null })),
      });
      toast(`“${body.name}” updated.`);
      setBusy(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to save dish.");
      setBusy(false);
    }
  }

  return (
    <div className={s.form}>
      <div className={s.formHead}>
        <h3 className={s.formTitle}>{dish.name}</h3>
        {dish.dish_number != null && <span className={s.formNum}>Dish #{dish.dish_number}</span>}
      </div>

      {error && <div className={s.formError}>{error}</div>}

      <label className={s.field}>
        <span className={s.label}>Name</span>
        <input className={s.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="Chicken Biryani" />
      </label>

      <div className={s.field}>
        <span className={s.label}>Photo</span>
        <div className={s.imageRow}>
          <div className={s.imageThumb}>
            {imageUrl ? <img src={imageUrl} alt="" /> : <span className={s.imagePh}>No photo</span>}
          </div>
          <div className={s.imageActions}>
            <input
              ref={imageInputRef}
              type="file"
              accept="image/jpeg,image/png"
              style={{ display: "none" }}
              onChange={(e) => onPickImage(e.target.files?.[0] ?? undefined)}
            />
            <Button variant="ghost" onClick={() => imageInputRef.current?.click()} disabled={uploadingImage}>
              {uploadingImage ? "Uploading…" : imageUrl ? "Replace photo" : "Upload photo"}
            </Button>
            {imageUrl && (
              <button type="button" className={s.imageRemove} onClick={() => setImageUrl("")}>
                Remove
              </button>
            )}
            <span className={s.imageHint}>JPG or PNG, at least 500×500. Meta needs a photo to publish.</span>
          </div>
        </div>
      </div>

      <div className={s.row}>
        <label className={s.field}>
          <span className={s.label}>Price (AED)</span>
          <input className={s.input} value={price} onChange={(e) => setPrice(e.target.value)} placeholder="20.00" />
        </label>
        <label className={s.field}>
          <span className={s.label}>Category</span>
          <input
            className={s.input}
            list="review-cats"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            placeholder="Biryani"
          />
          <datalist id="review-cats">
            {categories.map((c) => <option key={c} value={c} />)}
          </datalist>
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
          value={salePrice}
          onChange={(e) => setSalePrice(e.target.value)}
          placeholder="Optional — discounted price"
        />
      </label>

      <div className={s.variants}>
        <span className={s.label}>Sizes / serving variants</span>
        {variants.map((v, i) => (
          <div className={s.variantRow} key={i}>
            <input
              className={`${s.input} ${s.variantName}`}
              value={v.name}
              onChange={(e) => setVariant(i, { name: e.target.value })}
              placeholder="Large"
            />
            <input
              className={`${s.input} ${s.variantPrice}`}
              value={v.price_aed}
              onChange={(e) => setVariant(i, { price_aed: e.target.value })}
              placeholder="AED"
            />
            <button
              type="button"
              className={s.variantRemove}
              onClick={() => setVariants((vs) => vs.filter((_, idx) => idx !== i))}
              aria-label={`Remove variant ${i + 1}`}
            >
              ×
            </button>
          </div>
        ))}
        <button type="button" className={s.addVariant} onClick={() => setVariants((vs) => [...vs, { name: "", price_aed: "" }])}>
          + Add size
        </button>
      </div>

      <div className={s.formFooter}>
        <Button onClick={onSave} disabled={!canSave}>
          {busy ? "Saving…" : dirty ? "Save changes" : "Saved"}
        </Button>
      </div>
    </div>
  );
}
