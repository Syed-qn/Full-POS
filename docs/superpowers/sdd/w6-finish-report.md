# W6 Menu SoT — Finish Report (Tasks 4-6)

## Status: COMPLETE — all 6 evals graduated, 0 concerns blocking.

## Commits (this session, tasks 4-6; tasks 1-3 already landed prior)

- Task 4+5 combined: `26632e7` — feat(w6): whatsapp_enabled/slug filters + off-catalogue
  honest demotion (TX-45/F74/F97/TX-06)
- Task 6: `1793dfe` — test(evals): graduate all 6 W6 menu-SoT evals to permanent
  regression (0 xpass)

(Prior, already committed: task1 `4baf6ac`, task2 `3b5e856`, task3 `d825d21`.)

## Migration

None added. `whatsapp_enabled` (Boolean, default True) already existed on
`Dish` (`src/app/menu/models.py`) with its migration
`alembic/versions/l5e6f7a8b9c0_add_dish_whatsapp_enabled.py` already applied.
Only the READ paths (`_render_menu`, `_catalog_excludes_dish` in
`src/app/conversation/engine.py`) and the catalogue-basket WRITE path
(`handle_catalog_order` in `src/app/catalog/service.py`) were missing the
filter — no schema change was needed.

## Evals graduated: 6 / 6

All 6 xfail(strict=True) tests in `tests/evals/test_w6_menu_sot_evals.py` now
pass and have had their `xfail` markers removed:
1. `test_antihallucination_catches_non_catalogue_dish_names`
2. `test_one_dish_tenant_names_no_other_dish`
3. `test_whatsapp_disabled_dish_not_in_menu_render`
4. `test_whatsapp_disabled_dish_not_orderable`
5. `test_off_catalogue_dish_available_by_phone`
6. `test_slug_named_dish_absent_from_render_menu`

## whatsapp_enabled: DONE (column pre-existing, filters newly wired)

- `_render_menu`: added `Dish.whatsapp_enabled == True` to the query filter,
  plus a slug-name post-filter (`_SLUG_NAME = re.compile(r"^[a-z][a-z0-9_]*$")`)
  since `Dish` has no dedicated slug column.
- `_catalog_excludes_dish`: now returns `True` whenever `whatsapp_enabled` is
  `False`, in EVERY mode (previously the catalogue-membership checks only ran
  when catalogue mode was on; the WA-switch check is now unconditional).
- `catalog/service.py:handle_catalog_order`: a tapped catalogue-card item
  whose linked `Dish.whatsapp_enabled` is `False` is now routed to
  `unmapped` (rejected) instead of silently added.

## Task 5 fixes

- `_try_catalog_typed_order`'s off-catalogue reply reworded to mention phone
  ("It's available by phone — please call us to order it...") while keeping
  the existing "don't have" phrasing, preserving regression parity with
  `tests/catalog/test_catalog_mode_isolation.py::test_catalog_typed_noncatalogue_item_answered_not_catalogue`.
- Fixed a latent bug in `_looks_like_hallucinated_menu`'s candidate
  extraction (`_DISH_NAME_CANDIDATE`): the old regex let "and"/"&" glue two
  dish names into one non-matching run (e.g. "Lamb Ouzi and Seafood Platter"
  produced ONE unmatched 3+ word string instead of two 2-word candidates).
  Added `_CONJUNCTION_SPLIT` to segment the reply on and/&/, before matching,
  so each fabricated name is counted independently. Note: task 3's helper
  functions (`_canonical_dish_names`, `_looks_like_hallucinated_menu`) were
  additive only and are not yet wired into the live reply-swap call sites
  (`_looks_like_menu` remains the only live gate there) — out of scope for
  tasks 4-6, which target the whatsapp_enabled/slug/off-catalogue evals only.
- R-023 (single-token off-menu query, e.g. "beef") audited: already satisfied
  on the live path via `_execute_ai_add_item` → `"no_match"` → existing
  decline reply. The function with the ≥2-token requirement
  (`_handle_collecting_items`) is dead code, never called from
  `handle_inbound`. No code change required; noted in REGISTRY.md as a future
  cleanup candidate.

## Final suite run

`pytest tests/evals tests/conversation tests/catalog tests/menu -q`:
**336 passed, 7 xfailed, 0 failed** (7 remaining xfails are pre-existing,
unrelated to W6 — W2/W3/W8 workstreams per REGISTRY.md).

`pytest tests/evals -q` alone: **26 passed, 7 xfailed** — biryani eval #1
(`test_biryani_correction_final_state`) stays green; 0 unexpected xpass.

`ruff check` clean on all changed files.

## Files changed
- `src/app/conversation/engine.py` (whatsapp_enabled/slug filters, candidate
  extraction fix, off-catalogue reply)
- `src/app/catalog/service.py` (whatsapp_enabled guard in handle_catalog_order)
- `tests/evals/test_w6_menu_sot_evals.py` (xfail markers removed)
- `tests/evals/REGISTRY.md` (W6 graduation section added)

## BLOCKED / concerns
None. Pre-existing uncommitted dashboard batch-preview cruft in the working
tree was left untouched, per instructions — only the W6 files above were
staged and committed.
