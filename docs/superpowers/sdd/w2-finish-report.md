# W2 Finish Report — Cart Line Identity (T6/T7/T8)

**Date:** 2026-07-01  
**Branch:** remediation/w0-eval-harness  
**Base commits verified:** d814849 / 8f9a621 / 8fd2436 / a9fc603 / 209648e (W2 T1-5 ✓)

---

## Commit SHAs

| Task | SHA | Subject |
|------|-----|---------|
| T6 + T7 | `3c2b302` | `feat(engine): T6 — only/note routing in _try_catalog_typed_order (F82/RA-4/F101)` |
| T8 | `7d4ab72` | `test(evals): T8 — graduate W2 evals #2/#9/#10 (RA-4/F101/F82)` |

> T6 and T7 both modified `engine.py` and were staged in one commit. T7 changes
> (`_execute_ai_remove_item` → `CartService.remove`, `_execute_ai_update_qty` →
> `CartService.set_qty` / `CartService.set_note`) are included in the T6 commit.

---

## Evals Graduated

| # | Test name | Finding | Fix mechanism |
|---|-----------|---------|---------------|
| 2 | `test_catalogue_basket_double_masala_one_noted_line` (RA-4) | add_item on noted dish created duplicate | `_nid` regex detects "[note] in/for/on [dish_ref]"; Branch B routes to `CartService.set_note` |
| 9 | `test_pls_not_a_note` (F101) | politeness prefix stored in note | note-indicator heuristic (`_NOTE_STARTERS`) intercepts "extra masala" → `CartService.set_note` (normalization strips "pls") |
| 10 | `test_clear_cart_only_on_explicit_clear` (F82) | "only X" incremented rather than set | `is_only_intent` flag + Branch A routes to `CartService.set_qty` absolute set |

All three are now permanent regression guards (no `xfail`).

---

## Evals Left xfail + Why

| # | Test name | Why still xfail |
|---|-----------|----------------|
| 1 | `test_biryani_correction_final_state` | Full multi-turn correction needs W3 render + W4 router |
| 3 | `test_confirm_time_edit_total_matches` | W3 render: "make it 2" creates second line |
| 4 | `test_voice_order_five_items_all_present` | W1 voice STT not wired in harness |
| 5 | `test_modify_flow_remove_decrements` | W4 router: modify-flow remove not yet wired |
| 6 | `test_lakh_is_not_quantity_one` | W8 QuantityPolicy |
| 7 | `test_reaction_no_reply_no_mutation` | W8 UNKNOWN-type guard |
| 8 | `test_multilingual_catalog_request_sends_catalog` | W6/W8 fuzzy catalog keyword |
| 11 | `test_idempotent_redelivery_same_wa_message_id` | W8 dedup gate |

---

## Final Suite Summary

```
.venv/bin/pytest tests/ordering tests/conversation tests/catalog tests/evals -q
```

```
1 failed, 435 passed, 8 xfailed, 118 warnings
```

**The 1 failure (`test_cart_summary_shows_special_note_to_distinguish_duplicate_lines`)
was pre-existing before this session** (verified by `git stash` → run → `git stash pop`).
It stems from W2 T1 (`d814849`) which merged `add_item` by `(dish_id, variant_name)` —
the test expected two separate lines (plain + noted) that now collapse into one.
This test was already modified/broken entering this session and is NOT a regression
introduced by T6/T7/T8.

---

## Files Changed

| File | Change |
|------|--------|
| `src/app/conversation/engine.py` | T6: `_try_catalog_typed_order` — `is_only_intent` detection, "only/just/need" fillers, `_nid` note-in-dish pattern, note-indicator heuristic, Branch A (set_qty) + Branch B (set_note) before add_item. T7: `_execute_ai_remove_item` → `CartService.remove`; `_execute_ai_update_qty` → `CartService.set_qty` / `CartService.set_note` |
| `tests/evals/test_response_accuracy_suite.py` | Removed `@pytest.mark.xfail` from evals #2, #9, #10 |
| `tests/evals/REGISTRY.md` | Marked #2, #9, #10 as ✅ graduated; updated summary counts; updated eval #10 footer note |
| `understanding.txt` | Session log entry added |

---

## Blocked Items

None. All three T6/T7/T8 tasks complete and clean.

The following items are **deferred to later workstreams** (not blocked, just out of scope):
- `test_biryani_correction_final_state` (W3 + W4)
- `test_modify_flow_remove_decrements` (W4 router)
- `test_confirm_time_edit_total_matches` (W3 render)
- `test_cart_summary_shows_special_note_to_distinguish_duplicate_lines` pre-existing failure
  (needs a REGISTRY decision: either update the test to match the new merge-by-dish-id
  semantics from W2 T1, or add a variant_name to create truly separate lines)
