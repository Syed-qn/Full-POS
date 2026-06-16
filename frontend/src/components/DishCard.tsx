import type { DishOut } from "../lib/types";
import s from "./DishCard.module.css";

export function DishCard({
  dish,
  onToggle,
  onEdit,
}: {
  dish: DishOut;
  onToggle: (id: number, next: boolean) => void;
  onEdit?: (dish: DishOut) => void;
}) {
  const hasError = dish.dish_number === null || dish.price_aed === null;
  return (
    <div
      data-testid="dish-card"
      className={`${s.card} ${hasError ? s.error : ""} ${dish.is_available ? "" : s.dim} ${onEdit ? s.clickable : ""}`}
      onClick={onEdit ? () => onEdit(dish) : undefined}
    >
      <div className={s.top}>
        <span className={s.num}>#{dish.dish_number ?? "??"}</span>
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
        <span className={s.price}>AED {dish.price_aed ?? "—"}</span>
        {hasError ? (
          <span className={s.warn}>Needs number & price</span>
        ) : (
          onEdit && <span className={s.editHint}>Edit</span>
        )}
      </div>
    </div>
  );
}
