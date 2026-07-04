# Post-Add Quick-Action Buttons — Design Spec

**Date:** 2026-07-04  
**Status:** Approved  
**Scope:** Every added-to-cart confirmation (including WhatsApp catalogue basket) carries three quick-action buttons: Proceed to delivery, upsell (dish name or Suggestions), Clear cart.

---

## Problem statement

### Production transcript (catalogue basket)

Customer sends a catalogue cart (1× Chicken Soup, AED 15). Bot replies:

```
Got your basket 🎉

🛒 1x Chicken Soup (AED 15) | Subtotal: AED 15

Reply with more items, or send 'done' to proceed to delivery details.
```

**No interactive buttons.** Customer must type `done` manually. Screenshot: `IMG_D1C2BC52A732-1.jpeg`.

### Codebase gap

Typed / AI add paths in `src/app/conversation/engine.py` already call `_post_add_extras()` + `_send_buttons()` with:

1. `proceed_delivery` — Proceed to delivery  
2. `upsell_add:<dish_id>` or `suggest_dishes` — upsell  
3. `clear_cart` — Clear cart  

The **catalogue basket** path in `src/app/catalog/service.py` (`handle_catalog_order`) still uses `_send_text()` only (`prefix="catalog-cart"`). Tests cover the engine path but not catalogue basket.

---

## Goals

1. **Unified UX** — Every add-to-cart confirmation (catalogue basket, typed add, AI add, bundle/size applied, upsell re-add) shows the same three buttons.
2. **Smarter upsell** — Middle button shows a real dish name when grounded data exists; otherwise **Suggestions**.
3. **Deterministic grounding** — Upsell and Suggestions taps never invent dishes (spec R-003/R-005). No LLM on the Suggestions-button path.
4. **Menu-native specials** — Treat “chef special” / “restaurant special” as signals already present in menu text (category, name, description). No new dashboard flag.

## Non-goals

- New `chef_pick` column or Menu Manager toggle.
- Replacing the existing LLM suggestion sub-agent for free-text “suggest something” browse intents (only the **Suggestions button** path becomes deterministic).
- i18n / multilingual button labels (English only for this phase; matches current hardcoded replies).
- Changing checkout, address capture, or order-summary flows.

---

## User decisions (brainstorming 2026-07-04)

| Topic | Decision |
|-------|----------|
| Suggestions content (no personal history) | Top sellers — deterministic, DB-backed |
| Upsell priority | Hybrid: personal history → menu special → volume top seller → Suggestions button |
| Menu “special” | Detect from menu text; ignore if none found |
| Chef pick UI | None — use what’s written in the menu |

---

## Architecture (Approach 1 — extend `_post_add_extras`)

```
Any add-to-cart path
  → build cart summary line
  → _post_add_extras(session, conv, restaurant_id, order)
       → _upsell_dish_for_cart()   # NEW: unified resolver
       → return (upsell_body_line, buttons[3])
  → _send_buttons(body=confirmation + upsell_line, buttons=buttons)
```

**Catalogue basket change:**

```
handle_catalog_order (success path)
  - REMOVE: _send_text(..., "Reply with more items, or send 'done'...")
  + ADD:    _post_add_extras + _send_buttons (import from engine, same as typed-add)
```

**Tap handlers** (existing in `handle_inbound` BUTTON_REPLY block — no new ids):

| Button id | Action |
|-----------|--------|
| `proceed_delivery` | `_handle_done_checkout` (same as typing `done`) |
| `upsell_add:<dish_id>` | Validate dish (tenant, available) → `add_item` → fresh buttons |
| `suggest_dishes` | `_handle_top_sellers` (NEW deterministic path) |
| `clear_cart` | Empty draft order items → confirmation text |

---

## Upsell resolution (`_upsell_dish_for_cart`)

Returns `(Dish | None, source: str)` where `source` is `history` | `menu_special` | `top_seller` | `none`.

**Shared filters** (every candidate):

- Not already in current cart (`order.id`)
- `dish.is_available == True`
- `dish.whatsapp_enabled != False`
- Name not a slug placeholder (`_SLUG_NAME` guard)
- Passes `_catalog_excludes_dish` when catalogue mode is on
- Offer at most **once per draft** via `conv.state["upsell_shown_for"] == order.id` (existing behaviour)

**Priority chain** (first match wins):

### 1. Personal order history (existing)

Most-ordered dish from this customer’s **placed** orders (exclude `draft`, `cancelled`). Same SQL as current `_history_upsell_dish`.

### 2. Menu special (NEW)

Scan active menu dishes for “special” signals in **category**, **name**, or **description** (case-insensitive):

- `chef special`, `chef's special`
- `restaurant special`, `house special`
- `today's special`, `todays special`
- Category name contains `special` or `specials` (e.g. “Chef Specials”)

Pick the **first** dish matching filters above (stable order: category sort, then name). If no menu special exists → skip tier (do not invent).

### 3. Top seller by volume (NEW)

```sql
SELECT dish_id, SUM(qty) AS units
FROM order_items
JOIN orders ON orders.id = order_items.order_id
WHERE orders.restaurant_id = :rid
  AND orders.status NOT IN ('draft', 'cancelled')
  AND orders.created_at >= now() - interval '30 days'
GROUP BY dish_id
ORDER BY units DESC
LIMIT 10
```

Iterate results; return first dish passing shared filters and not in cart. If no orders in window → skip.

### 4. None → Suggestions button

Middle button: `{id: "suggest_dishes", title: "Suggestions"}` (unchanged).

When a dish is found, middle button:

```python
title = f"Add {dish.name}"
if len(title) > 20:
    title = title[:20]  # WhatsApp limit
{"id": f"upsell_add:{dish.id}", "title": title}
```

**Upsell body line** (when dish found):

```
You had {name} (AED {price}) last time. Add one? 😊     # history
Our {name} (AED {price}) is a favourite. Add one? 😊   # menu_special / top_seller
```

(Exact copy can be one generic line if we want less branching: “Try {name} (AED {price})? Add one? 😊”.)

---

## Suggestions button (`_handle_top_sellers`)

Invoked when customer taps `suggest_dishes` **or** when upsell resolver returned none and they chose Suggestions.

**Behaviour:**

1. Query top 3 dishes by 30-day volume (same SQL as tier 3, `LIMIT 3`).
2. Apply shared filters; exclude in-cart dishes.
3. If ≥1 result → send text list:

   ```
   Here are our bestsellers 😊
   • {name} — AED {price}
   • ...
   Tell me what you'd like and I'll add it 😊
   ```

4. If zero results (new restaurant, no orders) → fallback:

   ```
   Tell us what you're in the mood for 😊
   ```

   + `_send_menu_or_catalog` (existing fallback pattern).

**Does not call** `get_suggestion_agent()` on this path.

---

## Catalogue basket message shape

**Before:**

```
Got your basket 🎉

🛒 {cart}{notes}

Reply with more items, or send 'done' to proceed to delivery details.
```

**After:**

```
Got your basket 🎉

🛒 {cart}{notes}{upsell_line}
```

Plus **3 buttons** (no “send done” instruction as primary CTA).

Prefix stays `catalog-cart` for idempotency; `msg_type` becomes `buttons` via `_send_buttons`.

**Partial basket notes** (unmapped items, price mismatch) unchanged — still appended above buttons.

---

## Add-path coverage audit

| Path | File | Today | After |
|------|------|-------|-------|
| Catalogue basket | `catalog/service.py` | `_send_text` only | `_send_buttons` + `_post_add_extras` |
| Typed / AI add | `engine.py` | ✅ buttons | ✅ + extended upsell |
| Bundle / size applied | `engine.py` | ✅ buttons | ✅ + extended upsell |
| Catalog typed add | `engine.py` | ✅ buttons | ✅ + extended upsell |
| Upsell re-add tap | `engine.py` | ✅ refreshes buttons | unchanged |
| Cart edit (remove/set qty) | `engine.py` | text only | **out of scope** — edits are not “add to cart” confirmations |

---

## Error handling

- Upsell resolver wrapped in `try/except` — failure returns Suggestions button (never breaks add flow).
- `_handle_top_sellers` failure → menu/catalog fallback (same as `_handle_suggestions` empty path).
- Stale `upsell_add:<id>` tap (dish unavailable) → existing fallback to `_handle_suggestions`; **change to** `_handle_top_sellers` for consistency.
- Button title truncation at 20 chars (WhatsApp API limit).

---

## Testing plan

| Test file | Test | Asserts |
|-----------|------|---------|
| `tests/catalog/test_catalog_basket_buttons.py` (NEW) | `test_catalog_basket_carries_quick_action_buttons` | After `handle_catalog_order`, outbox payload has `buttons` with `proceed_delivery`, `clear_cart`, upsell or `suggest_dishes` |
| `tests/conversation/test_engine_ordering.py` | Extend upsell tests | Menu special dish picked when no history; top seller when no special; Suggestions when neither |
| `tests/conversation/test_engine_ordering.py` | `test_suggest_dishes_shows_top_sellers` | Tap `suggest_dishes` → deterministic list, no LLM mock called |
| `tests/conversation/test_engine_ordering.py` | Existing button E2E | Still pass (`proceed_delivery`, `clear_cart`, `upsell_add`) |

Regression: `pytest tests/catalog tests/conversation/test_engine_ordering.py -v`

---

## Implementation order (for writing-plans)

1. **PR1 — Upsell resolver** — `_menu_special_dish`, `_top_seller_dish`, refactor `_history_upsell_dish` → `_upsell_dish_for_cart`; update `_post_add_extras`; unit tests.
2. **PR2 — Catalogue basket buttons** — wire `catalog/service.py`; catalogue integration test (reproduces screenshot scenario).
3. **PR3 — Deterministic Suggestions** — `_handle_top_sellers`; route `suggest_dishes` button + stale upsell fallback; tests.

---

## Risks

| Risk | Mitigation |
|------|------------|
| “Special” false positives (dish name “Special Soup”) | Require phrase patterns (`chef special`, category `specials`), not lone word “special” in description |
| Long dish names truncate button title | Title `Add {name}` truncated to 20 chars; body line shows full name |
| New restaurant: no volume data | Suggestions → menu/catalog fallback |
| Cross-module import catalog→engine | Already imports `_build_cart_summary`, `_send_text`; add `_send_buttons`, `_post_add_extras` |

---

## Approval

- **User approved (brainstorming):** 2026-07-04 — Section 1 upsell priority; hybrid specials from menu text; catalogue gap; Approach 1.