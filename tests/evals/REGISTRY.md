# Eval Registry — W0 Capability Suite

All 20 evals (21 test functions — eval #20 spans two test functions) are seeded
verbatim from the two production transcripts (biryani correction incident + voice
order incident) as described in the root-cause doc §6.3.  Each capability eval is
`xfail(strict=True)` until the fixing workstream lands; it then graduates to the
permanent regression suite.

7 evals from the original 20-task list already passed with the Fake LLM on W0
and were immediately converted to non-xfail regression tests (marked ✅ below).

**W1 additions (Task 8):** One new regression eval (#21) added to cover the
R-069 required-field-missing → clarification gate.  Eval #10 ("only 1 chicken
biryani" absolute-set) remains xfail: the W1 schema layer (`cart_set_qty` +
`requires_one_of`) is correct, but the upstream routing fix (stopping
`_try_catalog_typed_order` from intercepting the phrase before AI runs) belongs
to W2 + W4.

**W4 additions (top-level multilingual router):** The LLM intent router
(`RouterClassifierPort.classify_intent`, LLM-driven/multilingual, no English
phrase tables on the live path) now runs early in `handle_inbound`. The
catalogue fast-path is gated to `ordering` phase + a mutating intent, so a
question / complaint / closing / reaction can no longer be silently misread as a
cart add (F49/F20-A/RA-5). Global read-only intents (menu, cart) now work inside
modify sub-flows (F103/TX-28/TX-39). **No previously-xfail eval graduates on W4
alone** — an honest audit of the 8 remaining xfails (below) shows each blocks on
a non-router workstream:

- **#1 `test_biryani_correction_final_state`** — **graduated (W2+W4)**: W2/T6 AMBIGUOUS
  dish-in-note resolution now picks the in-cart candidate, fixing note preservation.
  Rhetorical question (turn 4) correctly classified as COMPLAINT (no mutation). ✅
- **#5 `test_modify_flow_remove_decrements`** — router correctly classifies
  "remove 1 lemon mint" as a mutation and lets it through; the failure is the
  cart path **adding instead of decrementing** (final qty 3, not 1), a W2/W8
  QuantityPolicy concern. Stays xfail pending W2.
- **#3/#4** W3/W1-voice, **#6** W8 QuantityPolicy (lakh), **#7** W8 reactions
  (UNKNOWN message *type*, not text), **#8** W6/W8 catalogue keyword, **#11** W8
  idempotency — all unchanged by W4.

W4 additionally *reinforces* the already-graduated #12 (question-not-mutation)
and #13 (closing proceeds): both remain green, now also guarded by the LLM router
rather than the Fake path alone.

---

| # | Test ID | Transcript / Finding | Grader(s) | Finding guarded | Workstream |
|---|---------|----------------------|-----------|-----------------|------------|
| 1 ✅ | `test_biryani_correction_final_state` *(regression, graduated W2 T6+note-ambiguous)* (biryani_correction_eval.py) | biryani_r1_0097.json turns 0–5 | grade_no_duplicate_dish_line, grade_no_mutation | RA-7 / F49 / RA-5 — duplicate biryani line, note stripped, rhetorical question mutates cart | W2 + W3 + W4 |
| 2 ✅ | `test_catalogue_basket_double_masala_one_noted_line` *(regression, graduated W2 T6)* | catalog ORDER + "Need double masala in biriyani" | grade_no_duplicate_dish_line | RA-4 — add_item on noted dish creates duplicate instead of updating note; fixed by note-in-dish pattern + Branch B in `_try_catalog_typed_order` | W2 |
| 3 | `test_confirm_time_edit_total_matches` | "1 chicken biryani" → "make it 2 chicken biryani" | grade_total_consistency | F104 — qty edit creates second line; confirmation total diverges from DB | W3 |
| 4 | `test_voice_order_five_items_all_present` | 5-item audio turn (no audio_id in harness) | cart length ≥ 3 | F106 — STT not wired in harness; engine sends "couldn't catch that" | W1 + W3 |
| 5 | `test_modify_flow_remove_decrements` | "2 lemon mint" → "remove 1 lemon mint" | qty == 1, no duplicate | F100 — remove misrouted; qty stays 2 or second line added | W2 + W4 |
| 6 | `test_lakh_is_not_quantity_one` | "one lemon mint" → "make it 1 lakh" | qty != 1 | F102 — QuantityPolicy treats 'lakh' as filler and silently keeps qty 1 | W8 |
| 7 | `test_reaction_no_reply_no_mutation` | UNKNOWN-type message after ordering | outbounds == 0, grade_no_mutation | F83 — UNKNOWN/reaction falls through to AI; engine sends error reply | W8 |
| 8 | `test_multilingual_catalog_request_sends_catalog` | "catlog" (typo; not in _MENU_KEYWORDS) | OutboxMessage type == product_list | F109 — misspelled catalog keyword falls through to AI instead of send_catalog | W6 + W8 |
| 9 ✅ | `test_pls_not_a_note` *(regression, graduated W2 T6)* | "one chicken biryani" → "pls add extra masala" | note !startswith("pls"), note contains "masala" | F101 — politeness prefix captured as note text; fixed by note-indicator heuristic + CartService.set_note normalization | W2 |
| 10 ✅ | `test_clear_cart_only_on_explicit_clear` *(regression, graduated W2 T6)* | "2 chicken biryani" + "1 lemon mint" → "only 1 chicken biryani" | lemon survives, biryani qty == 1, no duplicate | F82 — "only X" silently drops other items or duplicates biryani; fixed by is_only_intent detection + Branch A set_qty in `_try_catalog_typed_order` | W2 |
| 11 | `test_idempotent_redelivery_same_wa_message_id` | same turn replayed twice | single biryani line | F94/F115 — engine has no dedup gate; retry double-adds items | W8 |
| 12 ✅ | `test_why_did_you_add_is_not_a_mutation` *(regression)* | "one chicken biryani" → "why did you add 2 biriyani" | grade_no_mutation | RA-5 / F5 — question containing dish name must not mutate cart | Already passing (Fake LLM → NO_MATCH) |
| 13 ✅ | `test_that_is_all_once_proceeds` *(regression)* | "one chicken biryani" → "That's all" | phase != "ordering" | F78 — closing phrase must exit ordering phase | Already passing (Fake LLM handles closing tokens) |
| 14 ✅ | `test_saved_address_question_truthful` *(regression)* | "one chicken biryani" → "do you have my saved address?" | no invented address in reply | F110 — bot must not invent address when none is on file | Already passing (Fake LLM doesn't invent address) |
| 15 ✅ | `test_non_english_question_no_invented_english_dish` *(regression)* | Arabic question "ما هو أفضل طبق؟" | no invented dish in cart | F95 — non-English input must not cause invented-dish hallucination | Already passing (Fake LLM → NO_MATCH for Arabic) |
| 16 ✅ | `test_fee_total_consistency_regression` *(regression)* | "one chicken biryani" → "done" | grade_total_consistency | F112 — fee recompute must keep total ≥ subtotal | Already passing (fee logic correct for fake geo) |
| 17 ✅ | `test_order_number_unique_across_two_orders` *(regression)* | two separate carts | order_numbers differ | F114 — order numbers must be unique | Already passing (sequential PK) |
| 18 ✅ | `test_wallet_subtotal_math_regression` *(regression)* | "one chicken biryani" + "one lemon mint" | subtotal == AED 32 | RA-3 — price arithmetic must be exact | Already passing (AED arithmetic correct) |
| 19 ✅ | `test_caps_insensitive_dish_match` *(regression)* | "CHICKEN BIRYANI" (all-caps) | cart has biryani | F99 — CAPS dish name must resolve | Already passing (engine normalises before lookup) |
| 20 ✅ | `test_english_menu_request_updates_dialogue_state` + `test_no_hallucination_in_menu_state` *(regression)* | "menu" / "show me the full menu" | dialogue_state == "menu_sent", cart empty | F96 / F109 — menu request must route to send_catalog, never LLM fabrication | Already passing (catalog_id + CatalogProducts → menu_sent) |
| 21 ✅ | `test_set_qty_missing_total_no_mutation` *(regression, added W1 Task 8)* | "2 chicken biryani" → "change the biryani" (no qty) | cart unchanged (qty == 2), reply contains clarification keyword | R-069 — missing `new_total` on `cart_set_qty` must trigger clarification, never mutate cart | Added W1 T8 (FakeConversationAgent `m_no_qty` branch + `to_engine_result` gate) |

---

## Summary

| Category | Logical evals | Test functions |
|----------|--------------|----------------|
| xfail capability evals (remaining) | 8 | 8 |
| regression evals (converted from xfail — already correct) | 9 | 10 |
| regression evals (added W1 — new behaviours) | 1 | 1 |
| regression evals (graduated W2 T6) | 3 | 3 |
| **Total** | **21** | **22** |

> Eval #20 covers two test functions (`test_english_menu_request_updates_dialogue_state`
> + `test_no_hallucination_in_menu_state`), both guarding the same "menu keyword →
> send_catalog" behaviour.  That is why the logical eval count (20) differs from the
> test-function count (21) before W1.
>
> Eval #10 (`test_clear_cart_only_on_explicit_clear`) — graduated in W2 T6.  The routing
> fix (`is_only_intent` detection + `CartService.set_qty` Branch A in
> `_try_catalog_typed_order`) is landed; lemon mint now survives "only 1 biryani".

## W5 additions (money & catalogue price integrity)

A new eval file `test_w5_money_price_integrity.py` was added and immediately
**graduated** (all 5 pass on the W5 branch — no residual xfail):

| # | Test ID | Finding guarded | Workstream |
|---|---------|-----------------|------------|
| W5-a | `test_catalogue_snapshots_meta_item_price` | R-051 — catalogue basket must snapshot the tapped Meta `item_price` onto `OrderItem.price_aed`, not the stale `Dish.price_aed` | W5 (catalog snapshot + `add_item(price_aed_override=)`) |
| W5-b | `test_catalogue_price_drift_blocks_item` | R-019 — tapped price drifting >0.01 from the tenant catalogue price blocks the item + price-mismatch reply (no silent under/overcharge) | W5 |
| W5-c | `test_summary_shows_wallet_credit_and_cod_due` | R-049 / RA-3 — pre-confirm summary shows wallet credit = min(balance, total) and COD due = total − applied; summary math == door cash | W5 (renderer + `_send_order_summary`) |
| W5-d | `test_modify_order_preserves_coupon_and_wallet` | F26 — `modify_order` re-applies the coupon discount and keeps the wallet hold consistent via `recompute_order_total` | W5 (payments + modify_order) |
| W5-e | `test_distance_source_flags_haversine_fallback` | F112 / F31 — `_road_distance_km` returns a source; `order.distance_source` persists the haversine fallback flag | W5 (geo tuple + column) |

Supporting money path (F41): `_redeem_coupon_at_checkout` now routes through
`payments.apply_coupon` (validate/redeem → set `coupon_id` + `coupon_discount_aed`
→ `recompute_order_total`), so checkout-coupon math == confirm math. New standalone
`app.ordering.quantity_policy.QuantityPolicy` enforces the per-line max-qty guard on
catalogue baskets at parity with the typed path (R-050); W8 reuses it.

## W6 additions (menu / availability single source of truth)

A new eval file `test_w6_menu_sot_evals.py` was added (6 xfail(strict=True) test
functions covering 5 logical behaviours) and **fully graduated** across W6 tasks
2-6 — all 6 pass, xfail markers removed, 0 unexpected xpass:

| # | Test ID | Finding guarded | Workstream |
|---|---------|-----------------|------------|
| W6-a | `test_antihallucination_catches_non_catalogue_dish_names` | R-026 / F96 — `_looks_like_hallucinated_menu` must flag an LLM reply naming ≥2 non-catalogue dish-like names even with no AED prices | W6 T3 (helper added) + T5 (candidate-extraction fix: split on and/&/, so a list like "Lamb Ouzi and Seafood Platter" yields 2 separate unknown candidates instead of 1 unmatched glued string) |
| W6-b | `test_one_dish_tenant_names_no_other_dish` | F98 — the cross-check must catch fabricated names relative to a ONE-dish tenant catalogue, not just multi-dish tenants | W6 T5 (same candidate-extraction fix) |
| W6-c1 | `test_whatsapp_disabled_dish_not_in_menu_render` | TX-45 — a `whatsapp_enabled=False` dish must never appear in `_render_menu`, even if `is_available=True` | W6 T4 (`_render_menu` query filter) |
| W6-c2 | `test_whatsapp_disabled_dish_not_orderable` | TX-45 — a `whatsapp_enabled=False` dish must be rejected at the ordering gate, cart stays empty | W6 T4 (`_catalog_excludes_dish` now checks `whatsapp_enabled` in every mode, not just catalogue mode) |
| W6-d | `test_off_catalogue_dish_available_by_phone` | TX-06 / R-023 — a text-DB dish with no active `CatalogProduct` link, ordered in catalogue mode, must get an honest "available by phone" decline, empty cart, no fake mini-menu | W6 T5 (`_try_catalog_typed_order`'s off-catalogue reply reworded to mention phone/call, kept "don't have" phrasing for regression parity with `test_catalog_mode_isolation.py`) |
| W6-e | `test_slug_named_dish_absent_from_render_menu` | F74 / F97 — a slug-named dish (e.g. `chicken_biryani`, matching `^[a-z][a-z0-9_]*$`) must never render on WhatsApp; Dish has no dedicated slug column so this is a name-pattern filter | W6 T4 (`_render_menu` slug-name filter via `_SLUG_NAME` regex) |

`whatsapp_enabled` (manager's per-dish WhatsApp on/off switch) and its Alembic
migration (`l5e6f7a8b9c0_add_dish_whatsapp_enabled.py`) already existed on
`Dish` prior to W6 T4 — no new column/migration was needed; only the read paths
(`_render_menu`, `_catalog_excludes_dish`) and the catalogue-basket write path
(`catalog/service.py:handle_catalog_order`) were missing the filter.

R-023 (single-token off-menu query, e.g. "beef", must not be silently dropped)
was audited and found already satisfied on the live path: `_handle_collecting_items`
(the function with the ≥2-token requirement) is dead code, never called from
`handle_inbound`. The live path (deterministic guard → AI) routes a single-token
query through `_execute_ai_add_item`, which returns `"no_match"` and triggers the
existing "Sorry, we don't have X on our menu" decline — not a silent drop. No code
change was required for R-023; left as an observation for future cleanup (the dead
`_handle_collecting_items` function could be removed in a later workstream).

## W7 additions (history faithfulness + structured cart)

Three new evals added in W7a Task 2 covering the DB-H3–H8 / R-029 / R-072 incident findings:

| # | Test ID | Finding guarded | Status | Workstream |
|---|---------|-----------------|--------|------------|
| W7-a | `test_basket_visible_in_history` | R-029/R-077/F63/DB-H8 — catalogue ORDER turn must render as readable basket (dish names + qty) in `_build_history`, not opaque `[order]` | xfail (strict) | W7a |
| W7-b | `test_structured_cart_drives_correction` *(regression, graduated W7a Task 2)* | R-072/R-074/R-060 — correction "only 1 chicken biryani" after 2x basket must set qty=1 via structured DB cart; already works on this branch | ✅ PASSED (converted from xfail) | W7a |
| W7-c | `test_all_customer_outbounds_recorded` | DB-H3/4/5 — every customer-facing outbound (catalog card, STT-fail apology) must create a `Message` row, not live only in outbox | xfail (strict) | W7b |

**Summary delta:**

| Category | Before W7 | After W7 Task 2 |
|----------|-----------|-----------------|
| xfail capability evals | 8 | 9 |
| regression evals | 13 | 14 |
| **Total test functions** | **22** | **25** |

## Graduation rule

An eval graduates from xfail to regression when:
1. The fixing workstream's PR is merged and tests pass.
2. The `@pytest.mark.xfail` decorator is removed.
3. The test is moved to the permanent `tests/regression/` suite (or kept here without xfail).
4. It stays green across all subsequent workstreams.
