import type { DishOut } from "../lib/types";
import s from "./DishCard.module.css";

export function DishCard({
  dish,
  onToggle,
}: {
  dish: DishOut;
  onToggle: (id: number, next: boolean) => void;
}) {
  const hasError = dish.dish_number === null || dish.price_aed === null;
  return (
    <div data-testid="dish-card" className={`${s.card} ${hasError ? s.error : ""}`}>
      <div className={s.top}>
        <span className={s.num}>#{dish.dish_number ?? "??"}</span>
        <button
          role="switch"
          aria-checked={dish.is_available}
          className={`${s.toggle} ${dish.is_available ? s.on : s.off}`}
          onClick={() => onToggle(dish.id, !dish.is_available)}
        >
          {dish.is_available ? "Available" : "Unavailable"}
        </button>
      </div>
      <div className={s.name}>{dish.name}</div>
      <div className={s.price}>AED {dish.price_aed ?? "—"}</div>
    </div>
  );
}
