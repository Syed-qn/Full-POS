import type { DishOut } from "../lib/types";
import s from "./DishCard.module.css";

export function DishCard({
  dish,
  onToggle,
  onEdit,
  onDelete,
  onWhatsapp,
  inReview,
  onWhatsappToggle,
}: {
  dish: DishOut;
  onToggle: (id: number, next: boolean) => void;
  onEdit?: (dish: DishOut) => void;
  onDelete?: (dish: DishOut) => void;
  /** Whether this dish is live on the WhatsApp catalogue. undefined → status unknown. */
  onWhatsapp?: boolean;
  /** Linked to a catalogue product Meta is still processing (image fetch/review). It is
      kept off WhatsApp until ready — shown with an "In review" pill, not "On WhatsApp". */
  inReview?: boolean;
  /** Manager flips the dish's WhatsApp presence on/off. When provided the badge becomes
      an interactive switch. */
  onWhatsappToggle?: (id: number, next: boolean) => void;
}) {
  // Manager's WhatsApp switch (default on for older backends).
  const waEnabled = dish.whatsapp_enabled !== false;
  // Three states only: OFF (hidden), On WhatsApp (live), or In review (enabled but not
  // confirmed live yet). "Enabled but not live" covers both a fresh publish Meta is still
  // processing AND a just-toggled-on dish whose catalogue mirror hasn't been pulled back
  // — both mean "not live yet", so they share the amber "In review" badge rather than a
  // separate, confusingly-similar "WhatsApp on".
  const waLabel = !waEnabled ? "WhatsApp off" : onWhatsapp ? "On WhatsApp" : "In review";
  const waClass = !waEnabled ? s.waOff : onWhatsapp ? s.waOn : s.waReview;
  const waTitle = !waEnabled
    ? "Turned off, so it is hidden from your WhatsApp catalogue. Tap to turn on."
    : onWhatsapp
      ? "Live on your WhatsApp catalogue. Tap to turn off."
      : inReview
        ? "Meta is still processing this dish's image. It goes live automatically once ready. Tap to turn off."
        : "Turned on — Meta is still processing it, so it isn't live yet. It goes live automatically; click Pull from Meta to check. Tap to turn off.";
  const hasError = dish.dish_number === null || dish.price_aed === null;
  // POS-owned dishes are read-only: POS is the source of truth for name/price/category, so
  // editing here would drift from (and be overwritten by) the next sync. Lock the Edit
  // button and the click-to-edit card; the WhatsApp + availability toggles still work.
  const fromPos = dish.pos_product_id != null;
  const canEdit = onEdit && !fromPos;
  // Delete is locked too: a deleted POS dish just reappears on the next sync, so removing
  // it here only causes confusion. Manage removals in the POS.
  const canDelete = onDelete && !fromPos;
  // When a dish offers serving sizes, show the price span (e.g. "AED 18 to 60")
  // instead of a single base price, so the manager sees the range at a glance.
  const variants = dish.variants ?? [];
  let priceLabel = `AED ${dish.price_aed ?? "?"}`;
  if (variants.length > 0) {
    const nums = variants.map((v) => Number(v.price_aed)).filter((n) => !Number.isNaN(n));
    if (nums.length > 0) {
      const lo = Math.min(...nums);
      const hi = Math.max(...nums);
      priceLabel = lo === hi ? `AED ${lo}` : `AED ${lo} to ${hi}`;
    }
  }
  return (
    <div
      data-testid="dish-card"
      className={`${s.card} ${hasError ? s.error : ""} ${dish.is_available ? "" : s.dim} ${canEdit ? s.clickable : ""}`}
      onClick={canEdit ? () => onEdit(dish) : undefined}
    >
      {/* Dish number is kept in the backend (ordering/FSM) but hidden from the
          manager UI — it's an internal identifier, not customer-facing. */}
      <div className={s.top}>
        {/* WhatsApp on/off switch. State reflects "On WhatsApp" (live), "In review"
            (enabled but not live yet — Meta still processing or awaiting a Pull), or
            "WhatsApp off" (manager turned it off → unlinked & hidden). Tapping flips it.
            Static badge when no toggle handler. */}
        {onWhatsappToggle ? (
          <button
            type="button"
            aria-pressed={waEnabled}
            aria-label={`WhatsApp: ${waLabel}`}
            className={`${s.wa} ${s.waBtn} ${waClass}`}
            title={waTitle}
            onClick={(e) => {
              e.stopPropagation();
              onWhatsappToggle(dish.id, !waEnabled);
            }}
          >
            {waLabel}
          </button>
        ) : waEnabled ? (
          <span className={`${s.wa} ${waClass}`} title={waTitle}>
            {waLabel}
          </span>
        ) : (
          <span />
        )}
        <button
          role="switch"
          aria-checked={dish.is_available}
          className={`${s.toggle} ${dish.is_available ? s.on : s.off}`}
          onClick={(e) => {
            e.stopPropagation();
            onToggle(dish.id, !dish.is_available);
          }}
        >
          <span className={s.dot} />
          {dish.is_available ? "Available" : "Unavailable"}
        </button>
      </div>
      <div className={s.name}>{dish.name}</div>
      {dish.description && <div className={s.desc}>{dish.description}</div>}
      <div className={s.priceRow}>
        <span className={s.price}>{priceLabel}</span>
        <div className={s.actions}>
          {hasError && <span className={s.warn}>Needs number & price</span>}
          {fromPos && (
            <span
              className={s.posTag}
              title="Synced from your POS. Name, price and category are managed in the POS and refresh on every sync, so editing is locked here."
            >
              From POS
            </span>
          )}
          {canDelete && (
            <button
              type="button"
              className={s.deleteBtn}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(dish);
              }}
            >
              Delete
            </button>
          )}
          {canEdit && (
            <button
              type="button"
              className={s.editBtn}
              onClick={(e) => {
                e.stopPropagation();
                onEdit(dish);
              }}
            >
              Edit
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
