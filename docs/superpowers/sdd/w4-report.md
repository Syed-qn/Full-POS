# W4 — Top-level multilingual router — Implementation Report

**Date:** 2026-07-01
**Branch:** main (no worktree)
**Baseline commit:** `8c98ed1`

## Precondition note

The prompt expected `tests/conversation tests/evals` = 447 passed / 8 xfailed.
This checkout's actual baseline at `8c98ed1` was **218 passed / 8 xfailed** (state
clean and green). Commit SHA matched exactly, so work proceeded; the "447" figure
did not match this checkout's scope. All incremental-safety gates were enforced
against the real baseline (0 new failures per task).

## Per-task commit SHAs

| Task | Commit | Summary |
|------|--------|---------|
| 1 — Intent classifier port + fake | `681a0f5` | `IntentLabel` enum (13 labels), `RouterClassifierPort.classify_intent(text, cart_context, phase)`, `MUTATING_INTENTS`/`NON_MUTATING_INTENTS`, `FakeRouterClassifier` (new file), LLM Claude/DeepSeek impls, `get_router_classifier()`. 14 tests. |
| 2 — Router in handle_inbound | `09aec1e` | `_router_classify_intent()` called early; catalogue fast-path only runs for a mutating intent. UNKNOWN/errors fall through to legacy flow. |
| 3 — Phase-gate catalog fast-path | `e153248` | Fast-path gated to `ordering` phase AND mutating intent (F49/F20-A/RA-5). |
| 4 — Correction ≠ mutation / question ≠ mutation | `dc2e9a0` | Contract tests: complaint naming a qty ("why did you add 2") is never checkout/add; correction ("only 1 biriyani") stays a mutating intent in ordering + confirm phases. |
| 5 — Global intents in every phase | `5c33f1b` | menu + cart queries answered inside modify sub-flows (F103/TX-28/TX-39); modify FSM state preserved across the read-only menu send. 2 tests. |
| 6 — Graduate W4 evals | `b5a2610` | Honest audit — no eval graduates on W4 alone; REGISTRY updated per-eval. |

## Design decisions

- **LLM-driven, multilingual live path.** `ClaudeRouterClassifier` /
  `DeepSeekRouterClassifier` prompt the model for a single `IntentLabel` — no
  English phrase tables on the live path. `FakeRouterClassifier` (a deterministic
  test double, like the existing `FakeCompletionDetector`) drives tests; it lives
  in a new file `src/app/llm/router_fake.py`, so `fake.py` (with its raw-string
  hazards) was not touched.
- **Behavior-preserving integration.** `UNKNOWN` and any classifier error map into
  `MUTATING_INTENTS`, so the router only ever *diverts* clearly non-mutating turns
  (question/complaint/checkout/reaction) away from the cart-mutating fast-path; it
  never blocks a legitimate order. This kept every task green with 0 new failures.
- **Phase-gate is safe here.** The concern that gating the fast-path to `ordering`
  would break the "first dish after hi" case is obsolete — the greeting handler now
  sets `dialogue_phase="ordering"` before returning. The full
  conversation+evals+catalog suite stayed green with the gate applied.

## Evals graduated / left xfail

**Graduated:** none (honest). No previously-xfail eval flips on W4 alone.

**Left xfail (with reasons):**

| # | Eval | Blocking workstream | Why W4 is insufficient |
|---|------|--------------------|------------------------|
| 1 | `test_biryani_correction_final_state` | W2 | Router half done (rhetorical Q no longer mutates); still fails on **note preservation** ("double masala" dropped) — a W2 dish/note-parse concern. |
| 3 | `test_confirm_time_edit_total_matches` | W3 | Confirmation total render/consistency. |
| 4 | `test_voice_order_five_items_all_present` | W1-voice + W3 | STT not wired in harness. |
| 5 | `test_modify_flow_remove_decrements` | W2/W8 | Router classifies "remove 1" as mutation correctly; cart path **adds instead of decrements** (final qty 3, not 1) — QuantityPolicy. |
| 6 | `test_lakh_is_not_quantity_one` | W8 | QuantityPolicy (lakh/crore). |
| 7 | `test_reaction_no_reply_no_mutation` | W8 | UNKNOWN message *type* (not text); handled outside the text router. |
| 8 | `test_multilingual_catalog_request_sends_catalog` | W6/W8 | Misspelled catalogue keyword → send_catalog. |
| 11 | `test_idempotent_redelivery_same_wa_message_id` | W8 | Dedup on `wa_message_id`. |

**Reinforced (already green, now also router-guarded):** #12
(`test_why_did_you_add_is_not_a_mutation`), #13 (`test_that_is_all_once_proceeds`).

## Final suite summary

`tests/conversation tests/ordering tests/catalog tests/llm tests/evals`:
**557 passed, 8 xfailed, 0 failed, 0 xpass.** `ruff check` on all changed files: clean.

## Files changed

- `src/app/llm/port.py` — `IntentLabel`, `RouterClassifierPort`, `MUTATING_INTENTS`, `NON_MUTATING_INTENTS`.
- `src/app/llm/router_fake.py` — **new** `FakeRouterClassifier`.
- `src/app/llm/claude.py` — `ClaudeRouterClassifier` (LLM enum, multilingual).
- `src/app/llm/deepseek.py` — `DeepSeekRouterClassifier`.
- `src/app/llm/factory.py` — `get_router_classifier()`.
- `src/app/conversation/engine.py` — `_router_classify_intent()`; router gate + phase-gate on the catalogue fast-path; global menu/cart intents inside modify sub-flow.
- `tests/conversation/test_intent_classifier.py` — **new**, 16 tests.
- `tests/conversation/test_modify_global_intents.py` — **new**, 2 tests.
- `tests/evals/REGISTRY.md` — W4 audit + per-eval notes.

## Deferred / BLOCKED

- **Task 2 "question/complaint → answer + re-show DB cart" (full form):** the router
  guarantees such turns never reach the cart-mutating fast-path and they continue to
  the phase-aware AI to answer. A *deterministic* forced cart re-show on every
  question was **not** added — it would change existing (green) AI replies and risk
  regressions; the no-mutation guarantee (the load-bearing half) is delivered.
- **Eval graduations #1/#5:** BLOCKED on W2 (note preservation; remove-decrement).
  The router (W4) side is complete; flip these when W2 lands.
- **Emoji/reaction *text* silent-drop:** deliberately not added (no test covers it;
  risk of silent-drop regression). The reaction eval (#7) is an UNKNOWN message
  *type* owned by W8.
