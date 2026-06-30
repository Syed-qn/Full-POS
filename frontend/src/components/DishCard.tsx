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
  const waLabel = !waEnabled
    ? "WhatsApp off"
    : onWhatsapp
      ? "On WhatsApp"
      : inReview
        ? "In review"
        : "WhatsApp on";
  const waClass = !waEnabled
    ? s.waOff
    : onWhatsapp
      ? s.waOn
      : inReview
        ? s.waReview
        : s.waPending;
  const waTitle = !waEnabled
    ? "Turned off, so it is hidden from your WhatsApp catalogue. Tap to turn on."
    : onWhatsapp
      ? "Live on your WhatsApp catalogue. Tap to turn off."
      : inReview
        ? "Meta is still processing this dish's image. It goes live automatically once ready. Tap to turn off."
        : "On for WhatsApp and publishes automatically. Tap to turn off.";
  const hasError = dish.dish_number === null || dish.price_aed === null;
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
      className={`${s.card} ${hasError ? s.error : ""} ${dish.is_available ? "" : s.dim} ${onEdit ? s.clickable : ""}`}
      onClick={onEdit ? () => onEdit(dish) : undefined}
    >
      {/* Dish number is kept in the backend (ordering/FSM) but hidden from the
          manager UI — it's an internal identifier, not customer-facing. */}
      <div className={s.top}>
        {/* WhatsApp on/off switch. State reflects "On WhatsApp" (live), "In review" (Meta
            still processing), "WhatsApp on" (queued), or "WhatsApp off" (manager turned it
            off → unlinked & hidden). Tapping flips it. Static badge when no toggle handler. */}
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
        ) : waEnabled && (onWhatsapp || inReview) ? (
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
          {onDelete && (
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
          {onEdit && (
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
