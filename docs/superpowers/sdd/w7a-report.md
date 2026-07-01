# W7a — Faithful History + Structured Context — Report

**Branch:** `remediation/w0-eval-harness` (worked on main checkout, per instruction).
**Base:** `4b11982` (W6 complete). **Plan:** `docs/superpowers/plans/2026-06-30-w7-history-db-faithfulness.md`, Tasks 1–7 (W7a only). **W7b (Tasks 8–13, outbound-recording/delivery-coupling) explicitly DEFERRED** — not started.

## Provenance note

A prior W7a attempt had already produced Task 2 (xfail evals) and Task 3
(ORDER `display_text`/`cart_snapshot`) as commits `24ade0f` / `7942140` on an
orphaned branch (`remediation/w7-history-db-faithfulness`, diverged from
`367472f`, never merged). Those two commits matched the plan exactly and were
verified clean, so they were **cherry-picked** onto this branch (conflict only
in `tests/evals/REGISTRY.md`, resolved by keeping both the W6 and W7 sections)
rather than re-authored. Tasks 4–7 were implemented fresh this session.

## Commits (chronological)

| SHA | Subject |
|---|---|
| `b574dbd` | test(evals): add W7 capability evals — basket-in-history, structured-cart correction, all-outbounds-recorded (xfail strict) *(cherry-picked, Task 2)* |
| `936076a` | feat(catalog): persist display_text + cart_snapshot on ORDER record (R-077/R-082/F63/DB-H8) *(cherry-picked, Task 3)* |
| `438b851` | refactor(engine): single _build_history with per-type branches, merge, configurable window (R-078/79/80/83/84, F55/56/62/67, DB-H2/7/12/13) *(Task 4)* |
| `72f5853` | feat(llm): DB-cart precedence line + structured cart_lines in Claude/DeepSeek prompts (R-072/073/074/076) *(Task 5, scoped down — see below)* |
| `99fea99` | fix(catalog): normalize phone in catalogue handler so basket + text share one thread (F71/R-027) *(Task 6)* |
| `9e45314` | test(evals): graduate basket-in-history to regression; structured-cart correction already graduated (Task 7) |

## Task 5 scoping decision

The plan's Task 5 asked for a new `_build_cart_state` + `context["cart_state"]`
and a `FakeConversationAgent` change to consume it. Investigation showed W2
already built this exact projection as `context["cart_lines"]`
(`engine._build_context`, ordering phase) and `FakeConversationAgent` already
resolves `"only 1 X"` from the DB cart via `cart_summary` —
`test_structured_cart_drives_correction` passed with **zero code change**
(confirmed in the Task 2 cherry-pick's own commit message). Per the session
brief ("if the plan has a structured-context task beyond W2's cart_lines... do
it minimally; else skip and note W2 already covers cart_lines"), Task 5 was
narrowed to the one real gap: the **production** prompts (`claude.py`,
`deepseek.py`) only rendered the prose `cart_summary`, with no structured,
ID-addressable cart view and no explicit DB-precedence instruction. Both
prompts now render `CART LINES` (JSON array with `cart_item_id`) next to
`CURRENT CART` plus an explicit "CURRENT CART is correct" precedence line
(R-072/R-074/R-076). No new `_build_cart_state` function was added — it would
have duplicated `_build_cart_state`... i.e. `cart_lines`/`CartService`.

## Ordering column kept: `created_at` (not `ts`)

Per the explicit warning in this session's brief, `_build_history`'s
`ORDER BY` was **left on `(Message.created_at.desc(), Message.id.desc())`**,
unchanged from before W7a. The previous failed attempt broke 30 tests by
switching to `Message.ts`. This session did not touch the ordering column at
all — only the per-type rendering, merge, and window logic changed — and the
full `tests/conversation` + `tests/evals` suites were run after every task to
confirm 0 regressions before each commit.

## Evals graduated

- `test_basket_visible_in_history` — **graduated** (Task 7): catalogue ORDER
  turns now render as `[sent catalogue basket: 2x Chicken Biryani]` instead of
  the opaque `[order]`.
- `test_structured_cart_drives_correction` — **graduated** (Task 2, on cherry-pick;
  re-verified green throughout Tasks 3–7): already worked via the existing
  `cart_summary`/`cart_lines` path.
- `test_all_customer_outbounds_recorded` — **left xfail(strict)**, W7b scope,
  deferred this session (not implemented).

`tests/evals/REGISTRY.md` updated: W7 section now shows W7-a and W7-b (evals)
as ✅ graduated, W7-c still xfail pending W7b.

## Final suite summary

- `tests/conversation tests/catalog tests/evals -q` → **313 passed, 8 xfailed**,
  0 failed, 0 unexpected xpass.
- Full repo suite (`.venv/bin/pytest -q`) → **1340 passed, 8 xfailed, 2 failed**.
  The 2 failures (`tests/ordering/test_customer_profile.py::test_profile_reports_usual_order_time`,
  `tests/ordering/test_order_detail.py::test_api_order_detail_includes_dispatch_explain`)
  are **pre-existing, out of W7a scope** — both are dashboard/dispatch
  `dispatch_explain`/order-detail features tied to the pre-existing
  "dashboard batch-preview" work-in-progress noted in the session brief
  (`config.py`'s `batch_preview_cache_*` fields, dispatch/main/routers cruft
  already present before this session started). No file this session touched
  (`config.py` conversation_history_limit addition, `engine.py`
  `_build_history`, `catalog/service.py`, `llm/claude.py`, `llm/deepseek.py`,
  and their tests) is imported by either failing test's code path.
- `.venv/bin/ruff check` on every file touched this session → **All checks
  passed** (one `E741` ambiguous-name lint on a comprehension variable was
  fixed inline before commit).
- `tests/evals -v` → 28 passed, 8 xfailed, 0 unexpected xpass;
  `test_biryani_correction_final_state` (the #1 biryani regression guard)
  stays green throughout.

## Files changed (W7a scope only)

- `src/app/config.py` — `conversation_history_limit: int = 10`.
- `src/app/conversation/engine.py` — `_render_history_content` + rewritten
  `_build_history`; call site drops the hardcoded `limit=10`.
- `src/app/catalog/service.py` — `_order_cart_snapshot` helper; ORDER record
  now carries `display_text`/`cart_snapshot`; phone normalized via
  `identity.phones.normalize_phone` before conversation/customer lookup.
- `src/app/llm/claude.py`, `src/app/llm/deepseek.py` — `CART LINES` +
  DB-precedence line in the ordering-phase system prompt; `json` import added
  to `claude.py`.
- `tests/conversation/test_build_history.py` (new),
  `tests/catalog/test_order_record_snapshot.py` (cherry-picked),
  `tests/catalog/test_catalog_phone_normalization.py` (new),
  `tests/llm/test_cart_state_prompt_precedence.py` (new),
  `tests/evals/test_response_accuracy_suite.py`, `tests/evals/REGISTRY.md`.

## BLOCKED / deferred

Nothing blocked within W7a scope. **W7b (Tasks 8–13)** — `messages.outbox_id`/
`delivery_status`/`ai_decision`/`state_snapshot` migration, `record_outbound`
helper for all customer-facing sends, outbox↔message coupling + `wa_message_id`
backfill, per-turn AI-decision/state-snapshot persistence, and graduating
`test_all_customer_outbounds_recorded` — is **explicitly deferred**, per this
session's scope instruction. It is pure storage/observability work per the
plan and does not gate anything W7a delivered.
