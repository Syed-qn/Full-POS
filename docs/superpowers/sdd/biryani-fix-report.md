# Biryani Note Fix Report — Eval #1 Graduation

**Date:** 2026-07-01
**Fix:** `src/app/conversation/engine.py` — W2/T6 AMBIGUOUS dish-in-note resolution
**Eval:** `tests/evals/test_biryani_correction_eval.py::test_biryani_correction_final_state`

---

## Which Turn Dropped the Note

**Turn 1 (index 1): "Need double masala in biriyani"** — the note was never set.

Evidence from per-turn cart snapshots:

| Turn | Text | Biryani notes |
|------|------|---------------|
| 0 | catalog basket | None |
| 1 | "Need double masala in biriyani" | None (BUG HERE) |
| 2 | "That's all" | None (phase -> address_capture) |
| 3 | "Only 1 biriyani" | None (address_capture, no mutation) |
| 4 | "Why did you add 2 biriyani" | None (COMPLAINT, no mutation) |
| 5 | "I need only 1 biriyani with double masala" | None (address_capture, no mutation) |

---

## Root Cause

`_try_catalog_typed_order` contains a W2/T6 pattern that recognises "[note] in/for/on [dish_ref]" phrases. It called `find_dish_matches(session, restaurant_id, "biriyani")` and only acted when the result was DIRECT.

The `seed_biryani_menu` fixture seeds two biryani dishes: Chicken Biryani and Mutton Biryani. When queried with "biriyani", pg_trgm gives similar scores to both and returns AMBIGUOUS (not DIRECT). Because the guard checked only for DIRECT, `dish` was never set, Branch B (`note and _in_cart`) never fired, and the note was silently dropped.

The AI fallback also could not match "need double masala in biriyani" (the word "masala" is treated as a foreign food word for both biryani candidates, producing NO_MATCH).

---

## The Fix

Added an AMBIGUOUS resolution path in `_try_catalog_typed_order`'s W2/T6 block: when the dish reference resolves AMBIGUOUS, iterate candidates and pick the first one already in the cart (RA-7).

With Chicken Biryani in the cart and Mutton Biryani not, the loop sets dish=Chicken Biryani and note="double masala". Branch B then calls `CartService.set_note`.

---

## Before/After Per-Turn Cart Rows

### Before fix

| Turn | Biryani qty | Biryani notes |
|------|-------------|---------------|
| 0 | 1 | None |
| 1 | 1 | None |
| 2-5 | 1 | None |

### After fix

| Turn | Biryani qty | Biryani notes |
|------|-------------|---------------|
| 0 | 1 | None |
| 1 | 1 | "double masala" |
| 2-5 | 1 | "double masala" (preserved) |

Final cart: Chicken Biryani qty=1, notes="double masala" — all 5 test assertions pass.
