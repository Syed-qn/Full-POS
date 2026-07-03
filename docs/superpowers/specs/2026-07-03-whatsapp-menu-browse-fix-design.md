# WhatsApp Menu Browse, Suggestions & Compaction Leak — Design Spec

**Date:** 2026-07-03  
**Status:** Approved  
**Scope:** Fix empty menu/suggestion promises in customer WhatsApp chat (catalogue + text-menu tenants), stop internal compaction JSON leaking to customers, align `context.txt` / runtime prompts, and add a focused suggestion sub-agent for open-ended recommend requests.

**Triggering transcript:** Customer asks for boneless chicken → “Suggest me something” → bot sends compaction JSON and/or filler (“Here’s our menu”) with no catalogue cards, dish list, or CTA. Screenshot confirms repeated empty promises in `post_order` after cancelled order #183.

---

## Problem statement

### Customer-visible failures

1. **Empty menu promises** — Bot says “Let me show you…” / “Here’s our menu” but only sends plain text (no WhatsApp catalogue `product_list`, no text dish list, no CTA).
2. **Browse intents ignored** — “OK show me”, “suggest me something” do not match `_is_menu_request()` (requires “menu” keyword). `menu_show` is blocked in `post_order` phase.
3. **Ingredient browse missing** — “I want boneless chicken” has no handler (unlike “do you have drinks?” category query).
4. **Compaction JSON leak** — Internal `system_summary` payload (`compacted_count`, `[Earlier conversation summary]`) appeared in the customer thread.

### Root causes (code)

| Failure | Mechanism |
|---------|-----------|
| Filler without menu | `_dispatch_action` sends `no_action` reply text only; `_looks_like_menu()` swaps only replies with ≥2 price lines |
| `post_order` trap | `ACTION_SPECS["menu_show"].phases == ("ordering",)` only; customer re-ordering after cancel stays in `post_order` |
| “show me” miss | `_is_menu_request()` requires `_MENU_KEYWORDS` substring (“menu”, “catalogue”, etc.) |
| No ingredient search | `_parse_category_availability_query()` expects “do you have X?” patterns, not “I want boneless chicken” |
| JSON leak | `system_summary` stored as `direction=outbound`; `_render_history_content` ignores `payload["summary"]`; LLM may echo structured JSON; no outbound sanitizer |

---

## Goals

1. **Deliver real menu content** whenever the bot promises to show menu or suggestions (catalogue cards OR capped text list).
2. **Support browse/suggest/ingredient intents** in both `ordering` and `post_order` (empty cart re-order path).
3. **Never send internal metadata** (`system_summary`, compaction JSON) to WhatsApp.
4. **Align prompts** — `context.txt` (goldmine) + `conversation_prompts.py` tell the LLM when to use `menu_show` vs short dish names; never output JSON summaries.
5. **Suggestion sub-agent (Approach C)** — For open-ended “suggest / recommend” requests, a focused LLM picks up to 3 **real** dishes from a grounded candidate list with one-line reasons; engine validates and formats the WhatsApp reply.

## Non-goals

- Changing catalogue sync / Meta product push.
- Full-menu re-ranking or ML popularity model (use menu order + optional `Dish.meta` later).
- Dashboard UI changes.
- Allowing `menu_show` during active order tracking with non-empty cart in `post_order` (status queries unchanged).

---

## Architecture

Two layers work together:

```
Customer message
    │
    ├─► [B] Deterministic guards (handle_inbound, before AI)
    │       • post_order + empty cart + browse intent → reset to ordering
    │       • menu browse intent ("show me", "suggest") → menu/suggest handler
    │       • dish search ("boneless chicken") → filtered list or catalogue category
    │       • explicit menu request (existing, broadened keywords)
    │
    ├─► [C] Suggestion sub-agent (when needed)
    │       • Input: capped menu candidates (names + categories only), customer text, browse_filter
    │       • Output: ≤3 {dish_name, reason} — validated against DB before send
    │       • Skipped when ≤3 deterministic matches (engine sends list directly)
    │
    ├─► Lead conversation agent (existing)
    │       • Prompt rules: menu_show for browse; never fake menu text
    │
    └─► [B] Safety nets (_dispatch_action, _send_text)
            • Menu-promise fulfillment if no_action + promise phrases
            • Outbound sanitizer blocks internal JSON
            • Compaction: system_summary as role=system in history only
```

### Mode matrix (catalogue vs text)

| Tenant mode | Full menu browse | Filtered browse (ingredient) | Suggestions |
|-------------|------------------|------------------------------|-------------|
| Catalogue (`catalog_ordering_enabled` + `catalog_id`) | `send_catalog()` product cards | `send_catalog_category()` if single category else intro text + cards for top category | Text list of ≤3 dishes + optional “tap catalogue above” if cards sent |
| Text menu | `_render_menu()` capped text | Capped bullet list (max 15) | Text list ≤3 with one-line reasons |

---

## Component design

### 1. Phase reset — `_maybe_reset_post_order_for_browse`

**When:** `phase == post_order`, cart empty (no draft items), customer message matches browse/order-browse intent.

**Action:** Set `dialogue_phase=ordering`, `dialogue_state=collecting_items`, clear `draft_order_id` / `pending_order_id`.

**Intents covered:** `_is_menu_request`, `_is_menu_browse_intent`, `_parse_dish_search_query`, `_has_food_order_intent` without qty (browse-only).

### 2. Intent detectors (engine.py)

**`_is_menu_browse_intent(text)`** — short (≤45 chars), no destructive cart tokens:

- Phrases: `show me`, `ok show me`, `show something`, `suggest`, `recommend`, `pick for me`, `what should i order`, `surprise me`
- Multilingual aliases added incrementally (Hindi/Urdu: `suggest karo`, Arabic: `اقترح`)

**`_parse_dish_search_query(text)`** — returns keyword phrase or `None`:

- Patterns: `i want X`, `something with X`, bare ingredient `boneless chicken`
- Exclude when `parse_qty_and_text` yields order intent with dish match ready for cart add
- Store `conv.state["browse_filter"]` for follow-up suggest turns

### 3. Handlers

**`_handle_menu_browse`** — calls `_send_menu_or_catalog()` with short intro; sets `menu_in_context=True`.

**`_handle_dish_search(session, conv, inbound, restaurant_id, keyword)`** — reuses category-query matching (`_item_matches_category_query`) against dish name + `description_customer` (max 3 lines per spec). Catalogue path mirrors `_handle_category_availability_query`.

**`_handle_suggestions`** — orchestrates B + C:

1. Load candidates: filter by `browse_filter` or last inbound; cap at 30 for sub-agent input.
2. If 0 matches → warm decline + offer full menu.
3. If 1–3 matches → deterministic bullet list (no sub-agent call).
4. If >3 or vague “suggest me something” → call `get_suggestion_agent().suggest(...)`.
5. Validate returned names via `find_dish_matches`; drop hallucinations.
6. Send WhatsApp text; if catalogue mode and single dominant category, also send category cards.

### 4. Menu-promise fulfillment (`_dispatch_action`)

If `action == no_action` and `reply` matches `_MENU_PROMISE_PATTERNS` and inbound was browse-related (or last assistant turn promised menu):

→ Replace/send via `_send_menu_or_catalog()`; optionally suppress duplicate filler.

Patterns: `here's our menu`, `let me show you`, `take a look`, `browse everything`, `view full menu` (without actual menu attachment in same turn).

### 5. Compaction hardening

**`_render_history_content`:** `system_summary` → return `payload["summary"]` prefixed `[Earlier conversation summary]`.

**`_build_history`:** Rows with `type == system_summary"` → `role: system` (OpenAI-compatible); never merge into assistant turns.

**`_is_internal_leak(text)` + `_send_text` guard:** Block bodies containing `compacted_count`, `"[Earlier conversation summary]"` as JSON, or `{"summary":` prefix; log warning; send recovery message + trigger browse handler if context warrants.

**Compaction record:** Keep `direction=outbound` for DB consistency but document as history-only (same as `cart_observation`).

### 6. Action schema

**`menu_show` phases:** extend to `("ordering", "post_order")`.

**Engine phase guard:** In `post_order`, allow `show_menu` only when cart is empty (same guard pattern as reset).

Optional canonical action **`menu_browse`** — deferred; reuse `menu_show` + deterministic handlers to avoid dispatcher churn.

### 7. Suggestion sub-agent (Approach C) — `src/app/llm/suggestion_agent.py`

Follow `complaint_agent.py` pattern:

**Port:** `SuggestionAgentPort.suggest(menu_candidates: list[dict], customer_text: str, browse_filter: str | None) -> dict`

**Output JSON:**
```json
{
  "intro": "short friendly line",
  "picks": [
    {"dish_name": "exact menu name", "reason": "max 1 line, no price"}
  ]
}
```

**Constraints (system prompt):**
- Pick 1–3 items from MENU CANDIDATES only; never invent dishes.
- No prices in reasons (spec § customer-facing descriptions).
- Max 3 lines total customer-facing output from intro + picks.
- If no good match, return empty `picks` and intro asking clarifying question.

**Providers:** `FakeSuggestionAgent` (tests), `DeepSeekSuggestionAgent`, `ClaudeSuggestionAgent`.

**Factory:** `get_suggestion_agent()` in `factory.py`; register in `port.py`.

**When invoked:** Only from `_handle_suggestions` — never on every turn (cost/latency guard).

### 8. Prompt updates

**Files:** `context.txt`, `src/app/llm/conversation_prompts.py` (keep in sync).

**MENU / BROWSING section additions:**
- `show me` / `suggest` / `recommend` → `action="menu_show"` (short reply); engine sends real menu.
- Ingredient browse (`boneless chicken`) → `no_action` with ≤3 real dish names from MENU lookup OR let engine send list.
- **Never** say “Here’s our menu” unless `action="menu_show"`.
- **Never** output JSON, `compacted_count`, or internal summaries in `reply`.

**POST_ORDER block:**
- Empty cart + food browse → same as ordering (re-order after cancel).
- Do not run status_query for browse intents.

**Post-edit:** Run `scripts/sync_prompt_kb.py` to refresh `var/prompt_kb/index.json`.

---

## Data flow (happy path)

**Boneless chicken → suggest:**

1. Inbound: “I want boneless chicken” → `_parse_dish_search_query` → `browse_filter="boneless chicken"` → filtered list (if ≤3) or partial list + state saved.
2. Inbound: “Suggest me something” → `_is_menu_browse_intent` → `_handle_suggestions` uses `browse_filter` → sub-agent picks 2–3 from candidates → validated list sent.
3. Inbound: “OK show me” → `_is_menu_browse_intent` → `_handle_menu_browse` → `send_catalog()` or text menu.

---

## Error handling

| Case | Behaviour |
|------|-----------|
| Catalogue send fails | Fall back to text menu (text mode path); never silent filler |
| Sub-agent timeout/error | Deterministic top-3 from filter order; log exception |
| Sub-agent hallucinated dish | Drop pick; if all invalid, send “Tell me what you’re in the mood for 😊” + menu |
| Internal JSON in reply | Sanitizer blocks; send menu browse recovery |
| `post_order` + non-empty cart | No phase reset; existing modify/status flows |

---

## Testing

| Test file | Cases |
|-----------|-------|
| `tests/conversation/test_menu_browse.py` | show me, suggest, post_order reset, catalogue + text mode |
| `tests/conversation/test_dish_search.py` | boneless chicken filter, browse_filter persistence |
| `tests/conversation/test_compaction_leak.py` | system_summary history role; sanitizer blocks JSON |
| `tests/conversation/test_suggestion_agent.py` | Fake agent, validation, 0/1/3 picks |
| `tests/llm/test_prompt_goldmine.py` | context.txt still ≥700 lines after edit |

**Regression:** Run `tests/conversation/test_engine*.py`, `test_compaction.py`, `test_prompt_kb.py`.

---

## Files touched (implementation)

| File | Change |
|------|--------|
| `src/app/conversation/engine.py` | Intents, handlers, guards, history, sanitizer |
| `src/app/llm/action_schema.py` | `menu_show` in `post_order` |
| `src/app/llm/suggestion_agent.py` | **New** sub-agent |
| `src/app/llm/factory.py` | `get_suggestion_agent()` |
| `src/app/llm/port.py` | `SuggestionAgentPort` |
| `src/app/llm/fake.py` | `FakeSuggestionAgent` |
| `context.txt` | Prompt rules |
| `src/app/llm/conversation_prompts.py` | Mirror prompt rules |
| `tests/conversation/test_menu_browse.py` | **New** |
| `tests/conversation/test_dish_search.py` | **New** |
| `tests/conversation/test_compaction_leak.py` | **New** |
| `tests/llm/test_suggestion_agent.py` | **New** |

---

## Success criteria

1. Repro transcript: “boneless chicken” → “suggest me something” → “OK show me” each produce **visible** menu content (cards or dish list) on WhatsApp.
2. No customer message contains `compacted_count` or compaction summary JSON.
3. Biryani (catalogue) and a text-menu test tenant both pass new tests.
4. `context.txt` and `conversation_prompts.py` agree on browse/suggest rules.
5. Suggestion sub-agent never returns dishes absent from menu candidates (validated in tests).