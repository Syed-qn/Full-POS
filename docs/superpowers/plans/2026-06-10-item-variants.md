# Item Variants / Sizes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax. TDD: failing test first, then implementation.

**Status:** PLANNED (not started). Authored 2026-06-10 from customer design feedback. Current menus are flat; this adds optional per-dish variants (e.g. Chicken Biryani → Regular / Family) with their own prices.

**Goal:** A dish may declare named variants, each with its own price. When a customer orders such a dish without naming a variant, the bot asks **one** follow-up ("Regular or Family?") before the item is priced and added. The order summary, cart, totals, kitchen ticket and audit all carry the chosen variant. Dishes WITHOUT variants behave exactly as today (zero regression).

**Architecture fit:** Backend stays the source of truth — the AI only extracts intent. Variant resolution and pricing happen in `ordering/service.py`, never in the model's free text. The variant question is a backend FSM step, not an AI-authored decision. Mirrors the existing add-item path.

**Spec:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` (§3 ordering FSM). Non-negotiable rules still apply: dish numbers + prices mandatory, customer-facing text never invents prices, descriptions ≤3 lines no price.

**Key design decisions (locked):**
- **Variant lives on `Dish`, priced per variant.** A dish carries an optional ordered list of `{name, price_aed, dish_number?}`. If the list is empty/null → no-variant dish (today's behaviour). Base `Dish.price_aed` is the default/"from" price and stays NOT NULL for activation rules.
- **`OrderItem` snapshots the chosen variant** (`variant_name`, and `price_aed` already snapshots the resolved price). No FK to a variant row — variants are JSONB on the dish, consistent with the snapshot pattern already used for `dish_name`/`dish_number`.
- **One question, backend-owned.** New conversation sub-state `awaiting_variant` holds the pending `{dish_id, qty}`; the customer's next message resolves it (matched against the dish's variant names via existing fuzzy matcher). A bare unmatched reply re-asks once, then defaults to the first/cheapest variant rather than looping.
- **AI prompt unchanged in structure.** The `take_action` tool still returns `{dish_query, qty}`. Variant disambiguation is NOT pushed into the tool schema (keeps intent extraction simple and avoids the model inventing variant names). If the customer DID name a size ("family biryani"), the matcher resolves dish+variant directly and skips the question.
- **No new top-level FSM state** — `awaiting_variant` is handled inside the existing collecting-items routing so greeting/reset/status intercepts keep working.

---

## Files touched

```
src/app/menu/models.py            Dish: + variants (JSONB, default list)
src/app/menu/schemas.py           DishIn/DishOut: + variants field, validation
src/app/menu/service.py           activation guard: each variant needs name+price
src/app/ordering/models.py        OrderItem: + variant_name (String, nullable)
src/app/ordering/service.py       add_item(variant=...); resolve_variant() helper
src/app/ordering/matching.py      match a query against a dish's variant names
src/app/conversation/engine.py    awaiting_variant sub-state; ask + resolve; summary line
src/app/llm/deepseek.py           (optional) prompt note: don't invent sizes
alembic/versions/<rev>_dish_variants.py   add columns + BEFORE UPDATE trigger n/a (no new table)
scripts/seed_dev.py               give Chicken Biryani Regular/Family variants for manual testing
tests/menu/test_variants.py       activation guard, schema validation
tests/ordering/test_variants.py   add_item with/without variant, pricing, resolve
tests/conversation/test_engine_variants.py   ask-once, named-size skips question, default-on-fail
```

---

### Task 1: Schema — variants on Dish, variant_name on OrderItem

**Files:** `src/app/menu/models.py`, `src/app/ordering/models.py`, new alembic migration

- [ ] **Step 1 (test first):** `tests/menu/test_variants.py::test_dish_persists_variants` — create a Dish with `variants=[{"name":"Regular","price_aed":"28.00"},{"name":"Family","price_aed":"55.00"}]`, reload, assert round-trip.
- [ ] **Step 2:** Add `variants: Mapped[list] = mapped_column(JSONB, default=list)` to `Dish`. Shape per element: `{"name": str, "price_aed": decimal-string, "dish_number": int|null}`.
- [ ] **Step 3:** Add `variant_name: Mapped[str | None] = mapped_column(String(128))` to `OrderItem`.
- [ ] **Step 4:** `alembic revision --autogenerate -m "dish_variants"`; verify it only ADDs nullable columns (safe, no backfill — existing dishes get `[]`). No new table ⇒ no `updated_at` trigger needed.
- [ ] **Step 5:** Register nothing new in `conftest.py`/`env.py` (no new model module). Run `alembic upgrade head` against dev + `restaurant_test`.

### Task 2: Activation guard + schema validation

**Files:** `src/app/menu/schemas.py`, `src/app/menu/service.py`

- [ ] **Step 1 (test):** `test_activate_blocked_if_variant_missing_price` — a dish whose `variants` has an entry without a price (or without a name) blocks menu activation, mirroring the existing "dish lacks number/price" rule.
- [ ] **Step 2:** `DishIn`/`DishOut` gain `variants: list[VariantIn]` with `VariantIn(name: str, price_aed: Decimal, dish_number: int | None)`. Validator: names unique per dish, price > 0.
- [ ] **Step 3:** Extend the activation completeness check in `menu/service.py` to iterate variants.

### Task 3: Ordering — resolve + price a variant

**Files:** `src/app/ordering/matching.py`, `src/app/ordering/service.py`

- [ ] **Step 1 (test):** `tests/ordering/test_variants.py` — (a) `add_item` on a no-variant dish unchanged; (b) `add_item(..., variant="Family")` snapshots `variant_name="Family"` and `price_aed=55.00`; (c) `resolve_variant(dish, "fam")` fuzzy-matches "Family"; (d) unknown variant → returns None (caller decides).
- [ ] **Step 2:** `resolve_variant(dish, query) -> variant_dict | None` in matching.py — reuse `normalize_name` against variant names.
- [ ] **Step 3:** `add_item(session, *, order, dish, qty, variant: dict | None = None)` — when variant given, snapshot its name + price; else use base `dish.price_aed`. Merge rule (existing): same `dish_id` **and** same `variant_name` merges qty; different variant = separate line.

### Task 4: Conversation flow — ask once, resolve, default

**Files:** `src/app/conversation/engine.py`

- [ ] **Step 1 (test):** `tests/conversation/test_engine_variants.py` — using FakeConversationAgent: (a) ordering "chicken biryani" when it has variants → bot asks "Regular or Family?" and sets `awaiting_variant`; (b) next msg "family" → item added at 55.00, state cleared; (c) ordering "family biryani" directly → no question, added at 55.00; (d) unmatched variant reply twice → defaults to first variant, item added, no infinite loop.
- [ ] **Step 2:** In `_execute_ai_add_item`: after resolving the dish, if `dish.variants` non-empty and no variant determined, store `conv.state["awaiting_variant"] = {"dish_id":…, "qty":…}` and send a ONE-line question listing variant names + prices. Do NOT add the item yet.
- [ ] **Step 3:** Early in `handle_inbound` customer routing (before the AI call), if `awaiting_variant` is set and inbound is TEXT: `resolve_variant`; on hit → `add_item(variant=…)`, clear state, confirm in ≤20 words; on miss → re-ask once (track `variant_retries`), then default to `variants[0]`.
- [ ] **Step 4:** `_send_order_summary` + `_build_cart_summary`: render `"  2x Chicken Biryani (Family) - AED 110"` when `variant_name` present.
- [ ] **Step 5:** Greeting/reset/STOP intercepts must still pre-empt `awaiting_variant` (a customer who types "hi" mid-question resets cleanly) — add `awaiting_variant`/`variant_retries` to the keys cleared on reset.

### Task 5: Seed + manual verification

**Files:** `scripts/seed_dev.py`

- [ ] **Step 1:** Give dish #1 Chicken Biryani `variants=[{"name":"Regular","price_aed":"28.00"},{"name":"Family","price_aed":"55.00"}]`.
- [ ] **Step 2:** Manual sim run: "2 chicken biryani" → "Regular or Family?" → "family" → cart shows `2x Chicken Biryani (Family) - AED 110`; "1 mango lassi" (no variants) → added directly (no question).
- [ ] **Step 3:** `ruff check`, full `pytest`, update `understanding.txt` with date/time bullet.

---

## Risks / call-outs
- **Activation rule interaction:** a variant without a price must block activation exactly like a base dish without a price (spec §). Covered in Task 2.
- **Matching ambiguity:** "biryani" matches multiple dishes AND the chosen dish has variants — resolve the dish first (existing arbiter), THEN ask the variant. Don't conflate the two questions.
- **Don't push variants into the AI tool schema** — keeps the model from inventing sizes; backend owns the canonical variant list.
- **Backward compatibility:** every `variants=[]` dish must behave bit-identically to today. The Task 3/4 tests assert the no-variant path is unchanged.
