# Inventory & Supply Chain — Design Specification

Date: 2026-07-07
Status: Approved (Traditional POS §17 Phase E, scoped)

## 1. Scope

Ingredient-level stock tracking with recipe-driven auto-deduction, low-stock
alerting, and waste logging. Vendor/PO management and theoretical-vs-actual
variance reporting are deferred — they need real vendor data and a purchasing
workflow this platform doesn't have yet (YAGNI until inventory tracking itself
is validated with real usage).

## 2. Data model

- `ingredients` — id, restaurant_id, name, unit (e.g. "kg", "pcs", "L"), current_stock (Numeric), low_stock_threshold (Numeric)
- `dish_ingredients` — id, dish_id FK, ingredient_id FK, quantity_per_dish (Numeric) — the recipe linking a dish to what it consumes
- `waste_log` — id, restaurant_id, ingredient_id FK, quantity (Numeric), reason, recorded_by

## 3. Flow

1. Manager sets up ingredients and recipes once (`POST /api/v1/ingredients`, `POST /api/v1/ingredients/{id}/recipe-links`).
2. On order confirm (`finalize_confirmation`, same hook point as KDS ticket creation), `deduct_for_order` walks each `OrderItem` → its dish's `DishIngredient` recipe rows → decrements `Ingredient.current_stock` by `qty_ordered * quantity_per_dish`. Same transaction as the confirm — if this fails, the whole confirm rolls back (never let stock and orders diverge).
3. `GET /api/v1/ingredients/low-stock` — ingredients where `current_stock <= low_stock_threshold`.
4. `POST /api/v1/ingredients/{id}/waste` — logs a waste entry AND decrements stock by the same amount (waste is a real stock loss, not just a log).

## 4. API surface (new `src/app/inventory/` module)

- `POST /api/v1/ingredients` — create
- `GET /api/v1/ingredients` — list with current_stock
- `GET /api/v1/ingredients/low-stock` — below threshold
- `POST /api/v1/ingredients/{id}/recipe-links` — link a dish + quantity_per_dish
- `POST /api/v1/ingredients/{id}/waste` — log waste + deduct stock
- `POST /api/v1/ingredients/{id}/restock` — manual stock addition (deliveries)

## 5. Testing

Unit: deduction math for a multi-item order; recipe lookup returns nothing gracefully for dishes with no recipe configured (deduction is opt-in per dish, not mandatory — most dishes may have no recipe yet). Integration: confirm an order with a configured recipe → stock decrements; low-stock query returns only items below threshold.

## Related
- `docs/TRADITIONAL_POS_SYSTEM.md` §17 Phase E
- Vendor/PO management and theoretical-vs-actual reporting deferred (see §1)
